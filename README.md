# 隐名三国 本地助手

隐名三国（TKA）本地网页版助手工具，通过多维度筛选武将信息，帮助玩家快速定位和猜对武将名称。

## 项目功能

- **武将数据库浏览**：展示所有武将的基本信息，包括姓名、类型、出生年份、故乡和各项能力值
- **多维度筛选**：
  - 按故乡筛选
  - 按武将名称搜索（支持模糊匹配）
  - 按游戏年份和年龄筛选（根据出生年份自动计算）
  - 按武将类型筛选（武将/武人/识士/文士/名士）
  - 按喜欢/厌恶关系筛选
- **武将类型自动计算**：根据能力值范围（统率、武力、智力、政治、魅力）自动计算武将可能的类型，一个武将可能具有多种类型
- **详情页查看**：展示武将完整信息，包括能力值可视化条形图、喜欢和厌恶的武将关系
- **一键复制**：点击武将名称可快速复制到剪贴板

## 项目结构

```
tka-local-helper/
├── index.html          # 主页面，包含完整的前端逻辑（HTML + CSS + JavaScript）
├── officers.js         # 武将数据的 JavaScript 格式，供 file:// 协议直接加载
├── officers.json       # 武将数据的 JSON 格式（数组）
├── officers.jsonl      # 武将数据的 JSONL 格式（每行一条记录）
├── scrape_officers.py  # Python 爬虫脚本，从官网爬取武将数据
└── README.md           # 项目说明文档
```

## 文件说明

### index.html
单文件前端应用，包含：
- 深色主题 UI 设计
- 武将列表展示与筛选
- 武将详情页
- 哈希路由支持（`#/officer/{id}`）
- 优先加载 `officers.js`（支持 file:// 协议直接打开），回退加载 `officers.json`（需本地服务器）

### scrape_officers.py
Python 爬虫脚本，从 [tka-officer.plotrick.com](https://tka-officer.plotrick.com) 爬取武将数据：

```bash
# 全量爬取
python3 scrape_officers.py

# 只爬前 5 名（调试）
python3 scrape_officers.py --limit 5

# 断点续爬
python3 scrape_officers.py --resume

# 切换语言
python3 scrape_officers.py --locale en
```

支持功能：
- 多语言支持（zh-CN/zh-TW/en/ja/ko）
- 多线程并发爬取（默认 8 线程）
- 断点续爬
- 自动生成 `officers.json`、`officers.jsonl` 和 `officers.js`

## 使用方法

### 直接打开（推荐）
直接用浏览器打开 `index.html` 即可使用，数据通过 `officers.js` 本地加载。

### 本地服务器
如果需要加载 `officers.json`：

```bash
python3 -m http.server 8000
# 然后访问 http://localhost:8000
```

## 武将数据字段

每条武将记录包含以下字段：

| 字段 | 说明 |
|------|------|
| `id` | 武将唯一标识 |
| `name` | 当前语言的武将名称 |
| `names` | 多语言名称（ko/en/ja/zh-CN/zh-TW） |
| `stats` | 能力值，每项为 `[最小值, 最大值]` 区间 |
| `birth_year` | 出生年份 |
| `death_year` | 死亡年份（可能为区间） |
| `hometown_id` | 故乡区域 ID |
| `hometown` | 故乡名称 |
| `liked` | 喜欢该武将的 ID 列表 |
| `hated` | 厌恶该武将的 ID 列表 |

## 筛选逻辑说明

### 武将类型判断规则
根据武将的五项核心能力值（统率/武力/智力/政治/魅力）的区间范围，判断其可能的类型：
- 若某项能力的最小值大于其他所有能力的最大值，则该项为唯一最高
- 若多项能力区间有重叠，则该武将可能属于多种类型
- 类型对应：统率→武将，武力→武人，智力→识士，政治→文士，魅力→名士

### 年龄计算
输入游戏年份和目标年龄后，根据武将的出生年份区间计算其在该游戏年份可能的年龄范围。
