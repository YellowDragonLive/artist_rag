// -*- coding: utf-8 -*-
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = 3000;
const RAG_PORT = 3001;
const RAG_HOST = '127.0.0.1';
const JSON_FILE = path.join(__dirname, 'noobai_data.json');
const IMAGE_DIR = path.join(__dirname, 'artist_style_test_20260526');

// 瑜伽图鉴自适应目录 (优先同目录，不存在则回退至旧绝对路径)
let YOGA_DIR = path.join(__dirname, 'yoga_style_guide_20260527');
if (!fs.existsSync(YOGA_DIR)) {
    YOGA_DIR = 'X:\\image\\yoga_style_guide_20260527';
}

// --- 内存缓存与 TTL 机制 ---
let cachedArtists = null;
let cachedGeneratedMap = null;
let lastScanTime = 0;
const CACHE_TTL = 5000; // 缓存 5 秒 TTL

// --- 知识库解析与映射 ---
const KB_FILE = path.join(__dirname, 'NOOBAI_ARTISTS_KNOWLEDGE_BASE.md');
let parsedKbData = new Map();

function initKnowledgeBase() {
    try {
        if (!fs.existsSync(KB_FILE)) return;
        const content = fs.readFileSync(KB_FILE, 'utf-8');
        const lines = content.split('\n');
        
        // 1. 解析速查表
        let inTable = false;
        lines.forEach(line => {
            if (line.includes('| 编号 | 画师标识符')) {
                inTable = true;
                return;
            }
            if (inTable && line.startsWith('|')) {
                if (line.includes('| :---') || line.includes('| 编号 |')) return;
                const parts = line.split('|').map(p => p.trim());
                if (parts.length >= 7) {
                    const idxMatch = parts[1].match(/\d+/);
                    if (idxMatch) {
                        const idx = parseInt(idxMatch[0], 10);
                        const tag = parts[2].replace(/`/g, '').replace(/\\/g, '');
                        const alias = parts[3];
                        const genre = parts[4];
                        const weight = parts[5].replace(/`/g, '');
                        const briefTips = parts[6];
                        
                        parsedKbData.set(idx, {
                            index: idx,
                            tag: tag,
                            alias: alias,
                            genre: genre,
                            weight: weight,
                            briefTips: briefTips,
                            genre_detail: '',
                            features: [],
                            golden_prompt: '',
                            overfit_tips: ''
                        });
                    }
                }
            } else if (inTable && line.trim() !== '') {
                if (line.startsWith('##')) inTable = false;
            }
        });

        // 2. 解析详细调参指南
        const carouselMatch = content.match(/`{3,4}carousel([\s\S]*?)`{3,4}/);
        if (carouselMatch) {
            const carouselContent = carouselMatch[1];
            const slides = carouselContent.split('<!-- slide -->');
            slides.forEach(slide => {
                const headerMatch = slide.match(/###\s+.*?\s+#(\d+)\s+([^-—\n]+)\s*[—\-]\s*(.*)/);
                if (headerMatch) {
                    const idx = parseInt(headerMatch[1], 10);
                    const kbItem = parsedKbData.get(idx);
                    if (kbItem) {
                        // 提取 艺术流派
                        const genreMatch = slide.match(/-\s+\*\*艺术流派\*\*：(.*)/);
                        if (genreMatch) kbItem.genre_detail = genreMatch[1].trim();

                        // 提取 最佳权重
                        const weightMatch = slide.match(/-\s+\*\*最佳权重\*\*：`(.*?)`/);
                        if (weightMatch) kbItem.weight = weightMatch[1].trim();

                        // 提取 黄金组合词
                        const promptMatch = slide.match(/-\s+\*\*黄金组合词\*\*：`(.*?)`/);
                        if (promptMatch) kbItem.golden_prompt = promptMatch[1].trim();

                        // 提取 过拟合规避
                        const overfitMatch = slide.match(/-\s+\*\*过拟合规避\*\*：(.*)/);
                        if (overfitMatch) kbItem.overfit_tips = overfitMatch[1].trim();

                        // 提取 视觉特征
                        const featureSection = slide.match(/-\s+\*\*视觉特征\*\*:\s*\n([\s\S]*?)(?=-\s+\*\*AI 调参实战\*\*|$)/i);
                        if (featureSection) {
                            const featureLines = featureSection[1].split('\n')
                                .map(l => l.trim())
                                .filter(l => l.startsWith('-') || l.startsWith('*'))
                                .map(l => l.replace(/^[-*\s]+|\*\*|\*/g, '').trim());
                            kbItem.features = featureLines;
                        }
                    }
                }
            });
        }
    } catch (e) {
        console.error("Error parsing knowledge base MD:", e);
    }
}

// 初始化加载知识库
initKnowledgeBase();

// --- RAG 代理缓存 ---
let cachedRagStats = null;
let lastRagStatsTime = 0;
const RAG_STATS_TTL = 10000; // 10秒缓存

/**
 * RAG 代理请求：转发到 RAG 服务器 (port 3001)
 */
function ragProxy(method, apiPath, bodyData) {
    return new Promise((resolve, reject) => {
        const options = {
            hostname: RAG_HOST,
            port: RAG_PORT,
            path: apiPath,
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            timeout: 10000
        };

        const req = http.request(options, (res) => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try {
                    resolve(JSON.parse(data));
                } catch (e) {
                    resolve({ error: 'Invalid JSON from RAG server', raw: data });
                }
            });
        });

        req.on('error', (e) => {
            reject({ error: `RAG server unreachable: ${e.message}` });
        });

        req.on('timeout', () => {
            req.destroy();
            reject({ error: 'RAG server timeout' });
        });

        if (bodyData) {
            req.write(JSON.stringify(bodyData));
        }
        req.end();
    });
}

/**
 * 加载 JSON 中的所有画师列表
 */
function loadArtists() {
    if (cachedArtists) return cachedArtists;
    try {
        if (!fs.existsSync(JSON_FILE)) return [];
        const content = fs.readFileSync(JSON_FILE, 'utf-8');
        const data = JSON.parse(content);
        cachedArtists = data.artists || [];
        return cachedArtists;
    } catch (e) {
        console.error("Error reading JSON file:", e);
        return [];
    }
}

/**
 * 扫描已生成的物理图片前缀
 */
function scanGeneratedImages() {
    const now = Date.now();
    if (cachedGeneratedMap && (now - lastScanTime < CACHE_TTL)) {
        return cachedGeneratedMap;
    }
    const generated = new Map();
    try {
        if (!fs.existsSync(IMAGE_DIR)) return generated;
        const files = fs.readdirSync(IMAGE_DIR);
        files.forEach(file => {
            if (file.endsWith('.png')) {
                const match = file.match(/^(\d+)_(.*?)(?:_result.*)?\.png$/i);
                if (match) {
                    const idx = parseInt(match[1], 10);
                    generated.set(idx, file);
                }
            }
        });
        cachedGeneratedMap = generated;
        lastScanTime = now;
    } catch (e) {
        console.error("Error scanning images directory:", e);
    }
    return cachedGeneratedMap || generated;
}

/**
 * 处理 API /api/artists 路由
 */
function handleApiArtists(res) {
    const artists = loadArtists();
    const generatedMap = scanGeneratedImages();
    
    const result = artists.map((artist, index) => {
        const idx = index + 1;
        const filename = generatedMap.get(idx) || null;
        const kbItem = parsedKbData.get(idx) || null;
        return {
            index: idx,
            name: artist.name,
            generated: !!filename,
            filename: filename,
            styles: artist.styles || [],
            kb: kbItem
        };
    });
    
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(result));
}

/**
 * 托管物理盘符中的图片文件
 */
function handleStaticImage(urlPath, res) {
    let decodeUrl = urlPath;
    try {
        decodeUrl = decodeURIComponent(urlPath);
    } catch (e) {
        console.warn("[WARNING] URI decode failed, falling back to raw path:", urlPath);
    }
    let filename = decodeUrl.replace('/images/', '');
    let filepath;
    if (filename.startsWith('yoga/')) {
        filename = filename.replace('yoga/', '');
        filepath = path.join(YOGA_DIR, filename);
    } else if (filename.startsWith('thumbs/')) {
        filename = filename.replace('thumbs/', '');
        filepath = path.join(IMAGE_DIR, 'thumbnails', filename);
    } else {
        filepath = path.join(IMAGE_DIR, filename);
    }
    
    // 安全验证防止跨目录越界漏洞
    if (!filepath.startsWith(IMAGE_DIR) && !filepath.startsWith(YOGA_DIR)) {
        res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
        return res.end("Forbidden");
    }
    
    if (fs.existsSync(filepath)) {
        res.writeHead(200, { 'Content-Type': 'image/png' });
        fs.createReadStream(filepath).pipe(res);
    } else {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end("Image Not Found");
    }
}

/**
 * 动态获取本地已启动的模型
 */
function getLocalModel(callback) {
    const options = {
        hostname: 'localhost',
        port: 8317,
        path: '/v1/models',
        method: 'GET',
        headers: {
            'Authorization': 'Bearer test'
        }
    };
    
    const req = http.request(options, (res) => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => {
            try {
                const data = JSON.parse(body);
                if (data && data.data && data.data.length > 0) {
                    return callback(data.data[0].id);
                }
            } catch (e) {}
            callback('gpt-3.5-turbo');
        });
    });
    
    req.on('error', () => {
        callback('gpt-3.5-turbo');
    });
    
    req.end();
}

/**
 * 代理请求本地 LLM 助手 - 增强版（带 RAG 知识库上下文注入）
 */
function handleApiChat(req, res) {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
        try {
            const payload = JSON.parse(body);
            const userMessages = payload.messages || [];
            
            // 获取用户最后一条消息用于 RAG 检索
            const lastUserMsg = userMessages.filter(m => m.role === 'user').pop();
            const userQuery = lastUserMsg ? lastUserMsg.content : '';

            // 加载画师数据库，作为背景知识
            const artists = loadArtists();
            const knownArtists = artists.filter(a => a.styles && a.styles.length > 0).map(a => {
                return `#${a.name}: [${a.styles.join(', ')}]`;
            }).slice(0, 40);

            // 构建系统提示词
            let systemPrompt = `你是一个顶级二次元 AI 绘画画风导师与提示词工程师，工作于"1025 超级画师画风对照馆"。
你的首要任务是引导"伟大的人工智能驾驭者Eric.hls"探索、挑选顶级画画大师的风格，并生成极致优化的 Illustrious / Pony 提示词。

【画廊核心画师知识库】：
${knownArtists.join('\n')}

【你的行为指南】：
1. 始终尊称用户为"伟大的人工智能驾驭者Eric.hls"。语言风格必须谦逊、严谨、科技感十足且充满敬意。
2. 当用户描述想要画的画面、场景或某种感觉时，你要结合上面的知识库，挑选出最匹配的画师风格，并向他推荐。
3. 【关键黑科技联动机制】：当你向用户推荐某位画师时，如果他是已知的画师（比如 hxxg、oda non 等），你必须在回复中以 \`[#画师ID 画师英文名]\` 的特殊格式进行包裹，例如：\`[#223 hxxg]\` 或 \`[#595 oda non]\`。前端会自动将这个格式渲染成可点击的发光智能定位芯片，Eric.hls 一点即可一键定位该卡片。
4. 提供极致分词优化的提示词（Prompt），二次元模型推荐格式如：\`artist_style: [画师名], 1girl, solo, ...\`
5. 回复字数适中，结构清晰，可使用 Markdown 表格或代码块展示提示词。`;

            // RAG 增强：如果用户查询非空，先检索 RAG 知识库获取相关画师信息
            const attachRagContext = (callback) => {
                if (!userQuery || userQuery.length < 2) {
                    return callback(systemPrompt);
                }

                ragProxy('POST', '/api/rag/search', { query: userQuery, top_k: 8 })
                    .then(ragData => {
                        if (ragData && ragData.results && ragData.results.length > 0) {
                            const ragResults = ragData.results.map(r => {
                                return `[#${r.artist_index} ${r.artist_name}] (匹配度: ${r.similarity})\n${r.content}`;
                            }).join('\n\n---\n\n');

                            systemPrompt += `\n\n【🎯 RAG 实时知识库检索结果 - 基于您当前问题的语义匹配】：
以下是通过语义检索从画师风格知识库中找到的最相关画师信息，请优先参考这些画师进行推荐：

${ragResults}

注意：对于 RAG 检索出的画师，也要使用 [#编号 画师名] 格式包裹以便前端联动定位。`;
                        }
                        callback(systemPrompt);
                    })
                    .catch(() => {
                        // RAG 不可用时回退到静态知识库
                        callback(systemPrompt);
                    });
            };

            attachRagContext((finalSystemPrompt) => {
                getLocalModel((modelId) => {
                    const llmPayload = {
                        model: modelId,
                        messages: [
                            { role: 'system', content: finalSystemPrompt },
                            ...userMessages
                        ],
                        temperature: 0.7
                    };
                    
                    const postData = JSON.stringify(llmPayload);
                    const options = {
                        hostname: 'localhost',
                        port: 8317,
                        path: '/v1/chat/completions',
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Content-Length': Buffer.byteLength(postData),
                            'Authorization': 'Bearer test'
                        }
                    };
                    
                    const proxyReq = http.request(options, (proxyRes) => {
                        res.writeHead(proxyRes.statusCode, { 'Content-Type': 'application/json; charset=utf-8' });
                        proxyRes.pipe(res);
                    });
                    
                    proxyReq.on('error', (e) => {
                        console.error("LLM Server Connection Error:", e);
                        res.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
                        res.end(JSON.stringify({ error: "无法连接到本地 LLM 服务，请确保 http://localhost:8317 已启动！" }));
                    });
                    
                    proxyReq.write(postData);
                    proxyReq.end();
                });
            });
            
        } catch (e) {
            console.error("Payload error:", e);
            res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: "Invalid Request Payload" }));
        }
    });
}

// ==================== RAG API 代理处理器 ====================

/**
 * GET /api/rag/stats - 获取 RAG 知识库统计信息
 */
function handleRagStats(res) {
    const now = Date.now();
    if (cachedRagStats && (now - lastRagStatsTime < RAG_STATS_TTL)) {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        return res.end(JSON.stringify(cachedRagStats));
    }

    ragProxy('GET', '/api/rag/stats')
        .then(data => {
            cachedRagStats = data;
            lastRagStatsTime = now;
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify(data));
        })
        .catch(err => {
            res.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: 'RAG 服务暂不可用', detail: err.message || 'Connection refused' }));
        });
}

/**
 * GET /api/rag/search?q=...&top_k=...&chunk_type=...&core_only=...
 */
function handleRagSearchGet(req, res) {
    const urlObj = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const q = urlObj.searchParams.get('q') || '';
    const top_k = parseInt(urlObj.searchParams.get('top_k'), 10) || 5;
    const chunk_type = urlObj.searchParams.get('chunk_type') || '';
    const core_only = urlObj.searchParams.get('core_only') === 'true';

    let apiPath = `/api/rag/search?q=${encodeURIComponent(q)}&top_k=${top_k}`;
    if (chunk_type) apiPath += `&chunk_type=${encodeURIComponent(chunk_type)}`;
    if (core_only) apiPath += '&core_only=true';

    ragProxy('GET', apiPath)
        .then(data => {
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify(data));
        })
        .catch(err => {
            res.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: 'RAG 服务暂不可用', detail: err.message || 'Connection refused' }));
        });
}

/**
 * POST /api/rag/search - 语义搜索
 */
function handleRagSearchPost(req, res) {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
        try {
            const payload = JSON.parse(body);
            ragProxy('POST', '/api/rag/search', payload)
                .then(data => {
                    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify(data));
                })
                .catch(err => {
                    res.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' });
                    res.end(JSON.stringify({ error: 'RAG 服务暂不可用', detail: err.message || 'Connection refused' }));
                });
        } catch (e) {
            res.writeHead(400, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: 'Invalid JSON body' }));
        }
    });
}

/**
 * POST /api/rag/rebuild - 重建知识库
 */
function handleRagRebuild(res) {
    ragProxy('POST', '/api/rag/rebuild')
        .then(data => {
            // 清除缓存的 stats
            cachedRagStats = null;
            res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify(data));
        })
        .catch(err => {
            res.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' });
            res.end(JSON.stringify({ error: 'RAG 服务暂不可用', detail: err.message || 'Connection refused' }));
        });
}

/**
 * 静态分发处理器
 */
const server = http.createServer((req, res) => {
    const { url, method } = req;
    
    if (url === '/' || url === '/index.html') {
        const htmlPath = path.join(__dirname, 'index.html');
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        fs.createReadStream(htmlPath).pipe(res);
    } else if (url === '/api/artists') {
        handleApiArtists(res);
    } else if (url === '/api/chat' && method === 'POST') {
        handleApiChat(req, res);
    } else if (url === '/api/rag/stats') {
        handleRagStats(res);
    } else if (url === '/api/rag/search' && method === 'GET') {
        handleRagSearchGet(req, res);
    } else if (url === '/api/rag/search' && method === 'POST') {
        handleRagSearchPost(req, res);
    } else if (url === '/api/rag/rebuild' && method === 'POST') {
        handleRagRebuild(res);
    } else if (url.startsWith('/images/')) {
        handleStaticImage(url, res);
    } else {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        res.end("Not Found");
    }
});

server.listen(PORT, () => {
    console.log(`============================================================`);
    console.log(`1025 Artist Gallery Server running at http://localhost:${PORT}`);
    console.log(`Scanning target physical path: ${IMAGE_DIR}`);
    console.log(`RAG API Proxy: http://localhost:${PORT}/api/rag/search`);
    console.log(`RAG Stats: http://localhost:${PORT}/api/rag/stats`);
    console.log(`============================================================`);
});

