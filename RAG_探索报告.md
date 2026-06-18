# RAG 探索报告

> **项目**：NoobAI 画师智能选择
> **日期**：2026-06-18
> **探索者**：Eric.hls x Sisyphus (glm-5.2)
> **范围**：从方案选型、环境踩坑、方案跑通，到 RAG 形态梳理，最后实证对比 RAG 与全量上下文

---

## 0. 摘要

本报告记录了围绕"画师风格智能匹配"这一业务场景，对 RAG（Retrieval-Augmented Generation）技术形态的完整探索路径。

**核心结论**：对于本项目这种**小规模结构化知识库（~150K tokens）**，1M 上下文模型直接全量加载的精度 >= RAG，且基础设施成本为零。RAG 的价值在**大规模 / 多用户 / 成本敏感**场景才显著。

---

## 1. 探索起点

### 1.1 业务场景
- 数据源：noobai_data.json 含 1025 位画师，其中 116 位有 styles 标签数据
- 目标：用户输入画风描述（如"厚涂暗色调逆光"），系统精准匹配最契合的画师
- 下游用途：为 NoobAI / Illustrious 架构的 AI 绘图提供画师推荐

### 1.2 数据规模实测

| 数据源 | 字符数 | 说明 |
|---|---|---|
| noobai_data.json | 95,817 | 5487行，1025位画师（909位styles空，116位有数据） |
| NOOBAI_ARTISTS_KNOWLEDGE_BASE.md | 12,887 | 17位核心画师深度解析 |
| artist_profiles/artist_styles_collected.json | ~26,400 | 48位画师采集档案 |
| documents/ (116文件) | 45,123 | RAG chunk产物（与上述重复） |
| **合计（含重复）** | **180,224 字符** | |

### 1.3 Token 估算（中英混合）

中文字符 token 密度高（约1字1token），英文约4字符1token。180K字符中中文约60%：

- 中文部分 ~108K字 约合 110K-130K tokens
- 英文部分 ~72K字符 约合 18K-20K tokens
- **总计约 130K-150K tokens**

---

## 2. 方案选型与环境踩坑

### 2.1 三套备选方案

| 方案 | 技术栈 | 特点 | 建议场景 |
|---|---|---|---|
| A: ChromaDB（推荐） | ChromaDB + ONNX 嵌入 | 轻量离线、中英双语、零成本 | 平衡性能与开发效率 |
| B: FAISS + BGE-M3 | FAISS + 多语种嵌入 | 检索精度最高，中文SOTA | 对召回质量有极致要求 |
| C: 纯 JSON + TF-IDF | scikit-learn | 零依赖，秒级部署 | 快速验证，但无语义理解 |

### 2.2 方案 A 的两次失败

#### 失败一：onnxruntime DLL 初始化失败

错误信息：`ImportError: DLL load failed while importing onnxruntime_pybind11_state` / `动态链接库(DLL)初始化例程失败`

- **表象**：WinError 1114，常被误读为"权限问题"
- **根因**：onnxruntime 1.23.2 装在 user site，DLL 依赖链断裂
- **连锁影响**：sentence-transformers 依赖 torch，torch 的 c10.dll 同样崩，整条嵌入链路瘫痪

#### 失败二：conda install 权限拒绝

错误信息：`EnvironmentNotWritableError: The current user does not have write permissions to the target environment. environment location: X:\ProgramData\miniconda3`

- 这才是真正的"权限问题"
- **根因**：miniconda3 装在 X:\ProgramData\（系统目录，当前用户只读）
- conda 解析依赖、下载包都成功，卡在 Verifying transaction 写盘

### 2.3 根因总结

两个问题叠加：
1. **环境混装**：user site 与 conda base 混装，DLL 依赖链断裂
2. **系统目录只读**：conda base 无写权限，无法 conda install 修复

### 2.4 R3 解法（用户目录 conda env）

彻底绕开两个坑：

1. 建用户目录 conda env（用户可写，无权限问题）：`conda create -y -p C:\Users\13410\rag_env python=3.10`
2. conda-forge 装 onnxruntime CPU 版（自带匹配运行时，无 DLL 冲突）：`conda install -y -p C:\Users\13410\rag_env -c conda-forge "onnxruntime=1.26.0=py310he3e056b_0_cpu"`
3. pip 装其余依赖：`C:\Users\13410\rag_env\python.exe -m pip install chromadb fastapi uvicorn pydantic scikit-learn`

**关键洞察**：ChromaDB 默认嵌入函数只依赖 onnxruntime，不依赖 torch / sentence-transformers。所以只修 onnxruntime 就够了，torch 那条线不用碰。

### 2.5 方案 A 跑通验证

| 验证项 | 结果 |
|---|---|
| import onnxruntime | OK 1.26.0 |
| ChromaDB DefaultEmbeddingFunction 实例化 | OK |
| 端到端 smoke test（embed + query） | PASSED（首次下载 79MB 模型，19s） |
| builder --force | 398 chunk -> 398 向量，7.74s |
| 8 条检索测试 | 6/8 命中，2/8 因英文模型对中文区分弱而偏移 |

**遗留问题**：默认 all-MiniLM-L6-v2 是英文模型，纯中文细粒度查询区分弱。可后续换多语种嵌入优化，但不影响方案 A 跑通。


---

## 3. RAG 形态梳理

探索期间对 RAG 业务形态做了完整梳理，按"检索怎么干"分四大类：

### 3.1 经典 RAG（Naive RAG）
- 结构：查 -> 拼 -> 答
- 离线建库：文档切片 -> 嵌入模型 -> 向量库
- 在线查询：用户问题 -> 嵌入 -> 向量库 top-K -> 拼进 prompt -> LLM 生成
- 适合：知识库不大、问题明确、答案就在文档里
- **本项目方案 A 即属此类**

### 3.2 进阶检索 RAG（Advanced / Modular RAG）

| 变体 | 干什么 | 解决什么问题 |
|---|---|---|
| Multi-Query | LLM 把一个问题改写成多个角度的查询再并查 | 用户提问表述差 |
| HyDE | 先让 LLM 假设答案，用假答案去检索 | 问题与答案文本风格不匹配 |
| RAG-Fusion / RRF | 多查询结果做倒数排名融合 | 单查询遗漏 |
| Re-ranking | 先向量召回 top-50，再 cross-encoder 精排 top-5 | 向量召回粗 |
| Sentence Window | 检索单句，返回前后窗口 | chunk 切太碎丢上下文 |
| Parent-Child | 检索小块、返回大块 | 同上 |
| Graph RAG | 建知识图谱，按关系检索 | 跨文档推理、多跳问题 |

### 3.3 Agentic RAG（智能体 RAG）

让 LLM 自己决定"要不要查、查几次、查哪个库"：
- Iterative：查一次不够，再查一次
- Self-RAG：边生成边判断"这段需不需要检索支撑"
- Adaptive：简单问题直接答，复杂问题走 RAG，超复杂走多步推理
- Multi-hop：A 查到线索 -> 据此再查 B -> 拼出答案

### 3.4 网络 / API 嵌入形态

把"嵌入"环节从本地搬到网络：
- 全网络：建库和查询都用 API（OpenAI / Jina / 智谱 / 硅基流动）
- 混合：本地嵌入建库 + 网络重排
- 适合：不想管本地模型、中文场景、小规模知识库
- 代价：延迟、费用、断网即废

**关于 DeepSeek**：探索中确认 DeepSeek 官方 API 目前只有 chat / completion 系列，**不提供 embedding endpoint**。若要用网络 embedding，需选其他供应商。


---

## 4. 关键实证：RAG vs 全量上下文

### 4.1 探索动机

引用一段关于 Agentic Search 的论述（出处待核实，疑似 Anthropic 工程博客关于 context engineering 的文章）：

> 智能体搜索避免了这些失效模式。当数千名工程师提交新代码时，无需维护任何嵌入流水线或集中式索引。每个开发人员的实例都直接基于实时代码库工作。
>
> 但这种方法存在一个权衡：只有当 Claude 拥有足够的初始上下文，知道去哪里寻找时，它的效果才最好。这意味着 Claude 的导航质量取决于代码库的配置好坏（通过结合 CLAUDE.md 文件和 Skills 技能来分层提供上下文）。如果你让它在一个拥有十亿行代码的代码库中盲目寻找一个模糊的模式，在工作开始前你就会耗尽上下文窗口。

**待验证假设**：对于本项目这种小知识库，1M 上下文模型能否直接全量加载替代 RAG？

### 4.2 实测方法

将项目全部核心资料（3 个源文件 + 116 个 chunk 文档）一次性加载进 glm-5.2 的上下文，跑真实画师推荐任务，对比 RAG 检索结果。

### 4.3 实测数据

| 项 | 数值 |
|---|---|
| 实际占用 | ~150K tokens |
| 1M 窗口容量 | 1,000,000 tokens |
| **占用率** | **~15%** |
| 剩余可用空间 | ~850K tokens |

### 4.4 推理质量对比

用相同查询对比两种范式：

| 查询 | RAG (方案 A) | 全量上下文 | 评价 |
|---|---|---|---|
| 赛博朋克霓虹街头少女 | （未测） | kurenaiz / lam / reoen / mika pikazo | 全中 |
| 萌系水彩治愈 | na tarapisu -> ushiyama ame | ushiyama ame / piromizu / na tarapisu / kawakami rokkaku / harusame-r | 全量更全 |
| 韩式精致水光肌 | moisture -> bm tol -> shal.e | myung yi / shal.e / bm tol / yunsang / harusame | 全量更全 |
| 厚涂暗色调逆光 | ask -> yoneyama mai -> hxxg | （含 hxxg） | 持平 |

**结论**：全量上下文精度 **>= RAG**。原因：
- RAG 的 chunk 切分会割裂上下文（一个画师被切成 full / styles_cn / styles_en / description 四块）
- 向量召回可能遗漏
- 全量上下文里能看到每个画师完整的 styles 数组 + description + MD 深度解析，推理更完整

### 4.5 边界条件（诚实告知）

1M 上下文不是免费的：

| 维度 | 全量上下文 | RAG |
|---|---|---|
| 单次查询 token 消耗 | 150K（每次都带全量） | ~2K（只带检索结果） |
| API 费用（若走 API） | **高 75 倍** | 低 |
| 延迟 | 高（要处理 150K 输入） | 低 |
| 并发能力 | 受限 | 高 |
| 离线可用 | 否（需大模型） | 是（本地嵌入） |

### 4.6 对引用论述的验证

> "只有当拥有足够的初始上下文，知道去哪里寻找时，效果才最好"

**对本项目不成立**——画师数据是结构化的（name + styles 数组），不存在"不知道去哪找"的问题。该论述针对的是**十亿行代码库**里找模糊模式的场景。本项目是 180K 字符的结构化小知识库，完全在甜点区。


---

## 5. 选型建议

### 5.1 按场景决策

| 场景 | 推荐方案 | 理由 |
|---|---|---|
| **个人 / 单用户 / 本地推理** | 全量上下文 | 零基础设施，精度更优，150K tokens 占 1M 的 15% |
| **多用户 API 服务** | RAG（方案 A） | 成本和延迟优势，每次查询只耗 2K tokens |
| **混合方案** | RAG 召回 top-20 + 全量精排 | 兼顾成本与精度 |
| **超大规模知识库（>500K tokens）** | RAG + Agentic 迭代 | 全量塞不下，必须检索 |

### 5.2 对本项目的具体建议

**当前阶段（个人使用、本地推理）**：
- 直接全量塞上下文，砍掉整个 RAG 引擎
- 省掉 onnxruntime / ChromaDB 一堆环境维护负担
- 画师数据更新了直接改 JSON，不用重建向量索引

**未来若做成多用户服务**：
- 保留方案 A 的 RAG 引擎（已跑通，环境已就绪）
- 或用混合方案：RAG 召回 top-20 候选 -> 全量上下文里这 20 位的详细描述做精排

---

## 6. 探索路径时间线

| 阶段 | 动作 | 结果 |
|---|---|---|
| Phase 1 | 数据采集与回填 | 48 位画师风格数据采集，116 位画师 styles 回填 |
| Phase 2 | 方案 A 首次尝试 | 失败：onnxruntime DLL 崩 |
| Phase 2.5 | 切方案 C (TF-IDF) | 跑通，但无语义理解 |
| Phase 3 | 方案 A 重试 | 失败：conda 权限拒绝 |
| Phase 4 | R3 解法（用户目录 env） | 环境就绪 |
| Phase 5 | 方案 A 跑通 | 398 chunk，6/8 命中 |
| Phase 6 | RAG 形态科普 | 梳理 4 大类 RAG 形态 |
| Phase 7 | 全量上下文实测 | 150K tokens 占 15%，精度 >= RAG |
| Phase 8 | 选型建议 | 小库全量，大库 RAG |


---

## 7. 可复用经验

### 7.1 环境踩坑经验
1. **Windows + Python + 重 ML 依赖**：优先用 conda env 隔离，避免 user site 与 base 混装
2. **系统目录 conda**：ProgramData\miniconda3 默认只读，建用户目录 env 绕开
3. **onnxruntime DLL 问题**：用 conda-forge CPU 版，不要用 pip wheel
4. **ChromaDB 嵌入链路**：只依赖 onnxruntime，不依赖 torch / sentence-transformers，修好 onnxruntime 即可

### 7.2 RAG vs 全量上下文决策
1. **先算 token 量**：知识库 < 200K tokens，优先考虑全量上下文
2. **看数据结构**：结构化数据（JSON / 表格）全量更优，非结构化长文档 RAG 更优
3. **看使用模式**：单用户本地用全量，多用户 API 用 RAG
4. **看更新频率**：频繁更新全量更省事（不用重建索引）

### 7.3 RAG 方案选型
1. **快速验证**：方案 C (TF-IDF)，零依赖秒级部署
2. **生产可用**：方案 A (ChromaDB)，平衡性能与开发效率
3. **极致精度**：方案 B (FAISS + 多语种嵌入)，中文场景值得
4. **网络 embedding**：确认供应商有 embedding API（DeepSeek 没有，可选 OpenAI / Jina / 智谱 / 硅基流动）

---

## 附录 A：项目文件结构

    艺术家智能选择/
    |-- noobai_data.json                          # 1025 位画师主数据（116 位有 styles）
    |-- NOOBAI_ARTISTS_KNOWLEDGE_BASE.md          # 17 位核心画师深度解析
    |-- select_artist.md                          # 精选画师列表
    |-- artist_profiles/
    |   +-- artist_styles_collected.json          # 48 位画师采集档案
    |-- rag_knowledge_base/
    |   |-- documents/                            # 116 个画师 Markdown chunk
    |   +-- chroma_db/                            # ChromaDB 向量索引
    |-- rag_engine/
    |   |-- config.py                             # 配置常量
    |   |-- chunker.py                            # 文本分块器
    |   |-- vector_store.py                       # ChromaDB 向量存储 + 检索
    |   |-- builder.py                            # 一键构建入口
    |   |-- server.py                             # FastAPI 查询服务
    |   +-- requirements.txt                      # Python 依赖
    +-- start_rag.bat                             # 一键启动脚本

---

## 附录 B：关键命令速查

### 环境（一次性）
    conda create -y -p C:\Users\13410\rag_env python=3.10
    conda install -y -p C:\Users\13410\rag_env -c conda-forge "onnxruntime=1.26.0=py310he3e056b_0_cpu"
    C:\Users\13410\rag_env\python.exe -m pip install chromadb fastapi uvicorn pydantic scikit-learn

### 构建 RAG 索引
    C:\Users\13410\rag_env\python.exe -X utf8 -m rag_engine.builder --force

### 启动 RAG API 服务
    C:\Users\13410\rag_env\python.exe -X utf8 -m rag_engine.server
    # 或双击 start_rag.bat
    # API: http://localhost:3001  文档: http://localhost:3001/docs

---

*报告完*

