# DepScope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 交付可运行的 Python AI 软件依赖调查产品，用 Neo4j 保存有来源的依赖路径，用 DeepSeek 解释证据，并公开可复现的评估结果。

**Architecture:** FastAPI 协调不可变快照导入、OSV 公告查询、图分析、证据检索和生成接口。Neo4j 保存快照内的依赖实例及公告版本，内容寻址文件目录保存原始证据；React 展示调查、比较及实验结果。生成使用 DeepSeek API，首版 embedding 使用 Ollama 的小型模型。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、httpx、Neo4j Community 5.26 LTS、jsonschema、packaging、packageurl-python、React、TypeScript、Vite、Cytoscape.js、Node 22、Docker Compose、pytest、Vitest、Playwright。

**Spec:** ../specs/2026-10-13-depscope-design.md。先读规格再读本计划；下列任务补充代码边界，不改变已确认的产品范围。

**Status:** 2026-10-13 用户回复“继续”，规格获确认。用户已选择“直接开发吧”，按 inline 方式执行；各任务实际完成情况记录于执行账本。

## Global Constraints

- Python／PyPI 软件包身份归一、CycloneDX 1.6 JSON 导入、deps.dev 公开依赖图导入。
- 单次上限为 10 MiB、10,000 个组件实例、50,000 条依赖边。
- Neo4j Community 5.26 LTS 系列；核心功能不依赖 Enterprise、APOC 或付费图算法插件。
- DEPENDS_ON 的两端必须属于同一快照，所有路径按 snapshot_id 过滤。
- 同项目、同来源原始文件 SHA-256 的重复导入返回已有导入结果。
- components 中没有对应 dependencies 条目的组件标为依赖未知；明确的 dependsOn 空数组代表来源声称无进一步依赖。
- 每批最多 100 个 OSV 查询，并发上限 4；HTTP 单次超时 20 秒；有界重试等待 2、4、8 秒，429 优先遵守 Retry-After。
- 每个结果最多展示 20 条代表路径和 200 个图节点；聚合计数不依据缩略视图计算。
- 证据切分最大为 2,000 个 Unicode 字符，重叠 200 字符；最终最多使用 10 个片段、12,000 字符。
- DeepSeek 默认官方端点 https://api.deepseek.com，默认模型 deepseek-flash，非思考模式，最多 1,024 个输出 token；执行前再次核验官方接口和计价。
- 首版向量服务使用 Ollama qwen3-embedding:0.6b；模型或维度改变时建立新的索引版本。
- 批量实验必须声明金额和调用数上限；超时或缺少用量时保留费用预留；交互会话初始上限为 20 次生成调用。
- 建立 200 道问题，60 道开发题、140 道冻结测试题；四种检索方法使用相同语料、模型、提示和证据预算。
- seed=20261013；bootstrap 按案例家族重采样 1,000 次。
- UI 主语言英语，支持中英文问题；凭据不得出现在前端、日志、仓库或评估记录中。
- 来源类型区分 public_resolution、observed_environment、constructed；目标规模、预期提升和演示案例不得充当已经完成的成果。

## Review Focus

1. 上传数据流超过 10 MiB，且 Content-Length 缺失或不实：按实际读取字节拒绝，不能留下已发布快照。任务 3、11。
2. 用户快速切换项目／快照后旧请求才返回：页面继续显示当前选项的数据，不将旧结果挂到新标题下。任务 12。
3. 新旧 embedding 模型维度相同：检索仍按模型与索引版本隔离，不能混入旧向量。任务 13。
4. API 超时后可能已收费，用户又重试：保留首个调用的预留费用，重试占用新的限额。任务 14。
5. 公告正文要求修改数据库或编造计数：只作为引用资料处理，工具权限和确定性统计不受正文影响。任务 15。

---

## 执行准备、文件结构与公共约定

执行前使用 using-git-worktrees 技能检查隔离环境。DepScope 是独立 Git 仓库，基线提交为 089be5c。按用户要求，仓库已迁至 /Users/wangzhe/Documents/Codex/DepScope，与课程作业完全分开。开发位于其 .worktrees/development 隔离工作树。

依赖安装、启动 Docker、下载 embedding 模型和使用 API 都在计划获确认后的执行阶段进行。配置仅读取项目内的 .env 及明确的环境变量；不搜索其他项目的密钥。没有凭据时继续非模型任务，真实 API 验收单独保持未完成。

| 路径 | 职责 |
|---|---|
| backend/src/depscope/runtime/ | 配置、结构化错误、应用生命周期、doctor |
| backend/src/depscope/identity/ | PyPI／PURL／PEP 440 身份 |
| backend/src/depscope/ingest/ | 数据模型、CycloneDX、deps.dev 解析及限制 |
| backend/src/depscope/sources/ | 原始证据、公开 HTTP、PyPI 版本、OSV |
| backend/src/depscope/graph/ | 迁移、快照、查询运行、任务与证据仓库 |
| backend/src/depscope/jobs/ | 单个修改队列、状态、取消、重启恢复 |
| backend/src/depscope/analysis/ | 路径、跨项目调查、快照比较和验证等级 |
| backend/src/depscope/retrieval/ | 证据切分、索引版本和四种检索 |
| backend/src/depscope/generation/ | DeepSeek、用量、费用预留、结构化输出 |
| backend/src/depscope/investigation/ | 调查范围、工具事实、引用与回答校验 |
| backend/src/depscope/evaluation/ | 语料清单、题集、冻结、实验、指标和报告 |
| backend/src/depscope/api/ | 各业务模块的 HTTP 路由与分页 |
| backend/tests/{unit,integration}/ | 离线行为验证、真实 Neo4j 集成 |
| frontend/src/{api,features,components}/ | 类型化请求、各业务页、共享显示组件 |
| frontend/tests/、frontend/e2e/ | 页面状态测试、真实产品流程 |
| schemas/cyclonedx/1.6/ | 固定的官方 schema 及其依赖，离线校验 |
| examples/evidence_assistant/ | 新建、锁定依赖的真实 API 示例应用 |
| artifacts/{corpus,benchmark,experiments,verification}/ | 来源和实际运行结果，不存私有凭据 |
| docs/{architecture,operations,evaluation,portfolio}/ | 数据字典、复现、实验、演示与简历材料 |

统一使用 UTC 保存时间、在界面按用户时区显示。DomainError 携带 code、message、pointers、retryable；HTTP 错误不回显供应商认证请求。实例的 local_id 是来源中的标识，inst_key 是 snapshot_id 与 local_id 的确定性组合；接口不允许客户端自行改变所属快照。

接口说明中的 PublicClient.get_json、OsvClient.query／advisory、MatchService.collect、ComparisonService.create、EmbeddingProvider.embed、GenerationProvider.generate、Investigator.answer、CorpusCollector.collect、ExampleAssistant.summarize 和 Worker.run_once 均为 async 方法，返回类型指 await 后的结果。纯解析、图遍历和仓库接口保持同步；异步服务以 asyncio.to_thread 调用同步数据库操作，不阻塞网络事件循环。

每项任务有独立测试循环。代码块给出关键测试和实现逻辑；任务内列出的其他检查使用相同接口增加独立断言，不能删除范围或用恒定返回值代替实际算法。所有包导入从安装后的 depscope 命名空间进行。pytest 命令在 backend 目录内运行，前端命令在 frontend 内运行。

三个可验证阶段：任务 1—8 完成数据与公告的可查询后端；任务 9—12 完成可操作的图谱产品；任务 13—18 完成 AI、独立实验和复现交付。

### 测试辅助接口的归属

以下辅助对象仅用于测试，不作为展示数据或实验成绩。测试工厂必须调用被测服务或构造其真实输入，不能直接返回测试预期结果。对应任务负责在 backend/tests/conftest.py 或 tests/helpers/ 下创建它们。

| 创建任务 | 辅助接口及具体职责 |
|---|---|
| 2 | snapshot_factory(id, local_ids, edge_pairs, root=None) -> Snapshot：由 Component／Edge 真正组装 source_kind=constructed 的图，source.digest 是构造资料字节的校验值 |
| 3 | bom：BOM 常量的 deepcopy；source_for(raw: bytes) -> SourceRef：计算给定 raw 的真实 SHA-256；不会固定同一个 digest 用于不同资料 |
| 4 | research_dir：仓库 docs/research/software_supply_chain 的 Path，从 backend/tests/conftest.py 的 parents[2] 定位 |
| 5 | repo：真实隔离 Neo4j 的 SnapshotRepository；public_snapshot_factory(project_id)：读取 experimental_dependencies.json 并调用 parse_depsdev；每个测试拥有独立项目并只清理该项目 |
| 6 | job_store：真实 JobStore；ready_snapshot：用 repo 与 public_snapshot_factory 发布完成的快照 |
| 7 | coordinates：2 个完整 Coordinate；mock_osv：tests/helpers/osv.py 的 respx 适配器，batch(rows)、single_page(token,row) 注册 HTTP 响应，client 为真实 OsvClient |
| 8 | advisory_factory(id, aliases=(), related=(), withdrawn=None) -> AdvisoryRevision：填充 modified、digest、source、summary、details 与 affected，不跳过模型校验 |
| 10 | comparison_inputs(before_status,after_status) -> (MatchRun,MatchRun,Snapshot,Snapshot)：同一规范包的两份完整图，before 与 after 的 PackageQuery 使用指定状态，matched 带一个实际构造来源支持的 Finding |
| 11 | client：create_app 加完整服务容器的 TestClient，后台任务可逐项 run_once；不会将核心业务路由全部 mock 掉 |
| 12 | deferred<T>() -> {promise,resolve,reject}；graphResponse(snapshotId,nodeNames) -> GraphView：补齐 edges、total_nodes、hidden_nodes、completeness 和完整 GraphNode 字段 |
| 13 | index_store：真实索引仓库；evidence：来自构造字节、具备位置与 SHA-256 的 EvidenceChunk 元组 |
| 14 | ledger：真实 BudgetLedger；fake_model.reply(payload)：只替代生成 HTTP 响应，不替代费用账本与引用验证 |
| 15 | investigator：使用真实工具／检索和 fake_model 的 Investigator；write_spy 监视所有仓库 publish、delete、refresh 变更入口，不能在只读问答中被调用 |
| 16 | corpus_factory(missing_year,resolution_error)：通过真实选择／采集逻辑和 respx 来源响应产生 CorpusManifest；example_assistant：真实示例应用服务对象 |
| 17 | benchmark：以有足够不同来源／字段位置的 constructed 单元案例调用 build_benchmark，只用于验证配额与划分；发布题集另由真实 CorpusManifest 创建 |

source_for 的核心实现如下，作为任务 3 的测试辅助代码；observed_at 使用固定测试时刻，不伪装为实时采集。

~~~python
@pytest.fixture
def source_for():
    def build(raw: bytes) -> SourceRef:
        return SourceRef(uri="fixture://constructed",
                         digest=hashlib.sha256(raw).hexdigest(),
                         observed_at="2026-10-13T00:00:00Z",
                         parser_version="test-v1")
    return build
~~~

依赖安装折入交付它所需要的任务；本计划没有要求为了配置文件、文档或提交本身编写镜像测试。逻辑测试检验可观察结果和真实错误条件，独立 oracle 只在图路径和基准标签上使用。

## Task 1: 可启动的服务、配置及错误契约

**Files:** Create backend/pyproject.toml、backend/src/depscope/__init__.py、backend/src/depscope/runtime/{config,errors,app,doctor}.py、backend/tests/unit/test_runtime.py、.env.example、.gitignore。

**Interfaces:** Produces Settings.from_env(env: Mapping[str,str]) -> Settings、Settings.public_summary() -> dict、DomainError(code: str, message: str, pointers: tuple[str,...]=(), retryable: bool=False)、create_app(settings: Settings) -> FastAPI。后续路由通过应用组合增加，不在模块导入时连接数据库或调用模型。

- [x] Step 1：创建测试运行所需的最小 Python 包配置，安装项目内开发环境；依赖包含 fastapi、uvicorn、pydantic、httpx、neo4j、jsonschema、referencing、packaging、packageurl-python，开发依赖为 pytest、pytest-asyncio、respx、ruff、networkx。pyproject 指定 asyncio_mode=auto；.gitignore 排除 .env、虚拟环境、运行时资料、私有上传和模型文件，保留 .env.example。运行配置实际安装成功后记录版本，最终冻结在任务 18。

~~~bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
~~~

- [x] Step 2：写出不依赖数据库的失败测试。

~~~python
def test_live_service_never_exposes_api_key():
    settings = Settings.from_env({"DEEPSEEK_API_KEY": "sentinel-secret"})
    client = TestClient(create_app(settings))
    assert client.get("/health/live").json() == {"status": "alive"}
    assert "sentinel-secret" not in repr(settings)
    assert "sentinel-secret" not in str(settings.public_summary())
~~~

- [x] Step 3：运行 pytest tests/unit/test_runtime.py -q，确认缺少运行契约导致失败。
- [x] Step 4：实现配置和存活端点；密钥字段 repr=False，public_summary 只返回配置状态，不返回值；doctor 只探测明确配置的服务，不发付费生成请求。

~~~python
def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="DepScope")
    app.state.settings = settings
    @app.get("/health/live")
    def live():
        return {"status": "alive"}
    return app
~~~

- [x] Step 5：复测配置缺失、非法端点、负限额和错误字段位置；启动服务访问 /health/live，结果保存到 artifacts/verification/runtime.json。
- [x] Step 6：提交 feat: add runtime configuration and service contract。

~~~bash
git add backend/pyproject.toml backend/src/depscope/runtime backend/src/depscope/__init__.py backend/tests/unit/test_runtime.py .env.example .gitignore
git commit -m "feat: add runtime configuration and service contract"
~~~

## Task 2: 身份归一和快照数据模型

**Files:** Create identity/{coordinates,versions}.py、ingest/models.py、tests/unit/test_identity.py、tests/unit/test_snapshot_models.py。

**Interfaces:** Produces Coordinate(ecosystem, name, version, raw_version)、Component(local_id, name, coordinate: Coordinate|None, dependencies_known: bool, pointer: str)、Edge(from_id,to_id,requirement: str|None,pointer: str)、SourceRef(uri,digest,observed_at,parser_version)、Snapshot(snapshot_id,project_id,source_kind,source,components,edges,root_id: str|None,environment: dict,issues: tuple)。Produces identify(name: str, version: str|None, purl: str|None) -> Coordinate|None、snapshot_key(project_id,source_kind,digest) -> str、instance_key(snapshot_id: str,local_id: str) -> str。模型采用 Pydantic strict／extra=forbid 契约，序列化保留 tuple 内容，发布后的不可变性由仓库控制。

- [x] Step 1：写失败测试，证明归一不掩盖冲突。

~~~python
def test_conflicting_purl_is_not_silently_preferred():
    assert identify("LangChain_Core", "0.1.23", None).name == "langchain-core"
    with pytest.raises(DomainError, match="COORDINATE_CONFLICT"):
        identify("langchain-core", "0.1.23", "pkg:pypi/requests@2.32.3")
    assert identify("opaque-library", None, None) is None
~~~

- [x] Step 2：运行 pytest tests/unit/test_identity.py tests/unit/test_snapshot_models.py -q，检查失败。
- [x] Step 3：实现规范名、PEP 440 可解析版本和 PURL 交叉校验。版本身份使用来源给出的规范版本字符串并保留原值；无法比较的版本为 opaque，不以猜测补齐。所有边的来源标识都必须存在。

~~~python
def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()

def snapshot_key(project_id: str, source_kind: str, digest: str) -> str:
    payload = json.dumps([project_id, source_kind, digest], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()

def instance_key(snapshot_id: str, local_id: str) -> str:
    payload = json.dumps([snapshot_id, local_id], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
~~~

- [x] Step 4：增加预发布／本地版本、不同来源相同版本实例、缺少根、重名 local_id 与悬空边断言，复测通过。
- [x] Step 5：提交 feat: define package identity and immutable snapshot contracts。

~~~bash
git add backend/src/depscope/identity backend/src/depscope/ingest/models.py backend/tests
git commit -m "feat: define package identity and immutable snapshot contracts"
~~~

## Task 3: CycloneDX 导入和完整性语义

**Files:** Create ingest/{limits,cyclonedx,schemas}.py、schemas/cyclonedx/1.6/、backend/tests/conftest.py、tests/unit/test_cyclonedx.py。

**Interfaces:** Consumes Task 2 models。Produces read_limited(chunks: Iterable[bytes], limit: int=10*1024*1024) -> bytes、async_read_limited(chunks: AsyncIterable[bytes],limit: int=10*1024*1024) -> bytes、parse_cyclonedx(raw: bytes, project_id: str, source: SourceRef, environment: dict) -> Snapshot、load_schema_registry(directory: Path) -> Registry。根包含 metadata.component；数量上限包含根和嵌套组件。

- [x] Step 1：写测试夹具及失败测试。bom 是下面字典的独立深拷贝。

~~~python
BOM = {
    "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
    "metadata": {"component": {"type": "application", "name": "fixture", "bom-ref": "root"}},
    "components": [{"type": "library", "name": "requests", "version": "2.32.3", "bom-ref": "lib"}],
    "dependencies": [{"ref": "root", "dependsOn": ["lib"]}],
}

def test_absent_dependency_record_is_unknown(bom, source_for):
    raw = json.dumps(bom).encode()
    snap = parse_cyclonedx(raw, "p", source_for(raw), {})
    assert not next(c for c in snap.components if c.local_id == "lib").dependencies_known
    bom["dependencies"].append({"ref": "lib", "dependsOn": []})
    raw = json.dumps(bom).encode()
    snap = parse_cyclonedx(raw, "p", source_for(raw), {})
    assert next(c for c in snap.components if c.local_id == "lib").dependencies_known

def test_stream_limit_uses_observed_bytes():
    with pytest.raises(DomainError, match="UPLOAD_TOO_LARGE"):
        read_limited(iter([b"a" * 6_000_000, b"b" * 6_000_000]))
~~~

- [x] Step 2：运行 pytest tests/unit/test_cyclonedx.py -q，确认失败。
- [x] Step 3：保存官方 bom-1.6.schema.json 和实际引用的官方相邻 schema，记录校验值，Registry 仅从本地映射解析引用。解析前限制字节；schema 校验后递归展开组件，检查重复 bom-ref、坐标冲突和悬空 ref；位置用 JSON Pointer 返回。

~~~python
def read_limited(chunks: Iterable[bytes], limit: int = 10 * 1024 * 1024) -> bytes:
    output = bytearray()
    for chunk in chunks:
        if len(output) + len(chunk) > limit:
            raise DomainError("UPLOAD_TOO_LARGE", "Upload exceeds 10 MiB")
        output.extend(chunk)
    return bytes(output)

async def async_read_limited(chunks: AsyncIterable[bytes],
                             limit: int = 10 * 1024 * 1024) -> bytes:
    output = bytearray()
    async for chunk in chunks:
        if len(output) + len(chunk) > limit:
            raise DomainError("UPLOAD_TOO_LARGE", "Upload exceeds 10 MiB")
        output.extend(chunk)
    return bytes(output)
~~~

- [x] Step 4：验证 1.7 格式拒绝、根与嵌套重名、未知生态、明确空依赖、循环、组件／边上限以及 malicious externalReferences 不引发网络请求；复测通过。
- [x] Step 5：提交 feat: import CycloneDX with explicit completeness states。

~~~bash
git add backend/src/depscope/ingest schemas backend/tests
git commit -m "feat: import CycloneDX with explicit completeness states"
~~~

## Task 4: 原始证据、deps.dev 和固定版本选择

**Files:** Create sources/{records,http,retry,pypi,depsdev}.py、ingest/depsdev.py、tests/unit/test_public_sources.py、tests/unit/test_records.py。

**Interfaces:** Produces RecordStore.put(raw: bytes, uri: str, observed_at: str) -> SourceRef、RecordStore.get(digest: str) -> bytes、PublicClient.get_json(uri: str) -> dict、select_versions(metadata: dict, cutoff: datetime) -> tuple[str,...]、parse_depsdev(raw: bytes,project_id: str,source: SourceRef) -> Snapshot。公共重试接口 async request_with_retry(client: httpx.AsyncClient,method: str,uri: str,payload: dict|None,cancelled: Callable[[],bool]) -> httpx.Response。URI 只由固定 deps.dev／PyPI 坐标构造。

- [x] Step 1：用已保存真实样本写失败测试。

~~~python
def test_public_graph_preserves_instance_indices(research_dir, source_for):
    raw = (research_dir / "experimental_dependencies.json").read_bytes()
    snap = parse_depsdev(raw, "public-demo", source_for(raw))
    assert len(snap.components) == 41 and len(snap.edges) == 72
    assert snap.root_id == "0"
    assert len({c.local_id for c in snap.components}) == 41
~~~

- [x] Step 2：运行 pytest tests/unit/test_public_sources.py tests/unit/test_records.py -q。
- [x] Step 3：RecordStore 以 sha256 的前两位分目录，临时文件写完校验后原子替换；每次观察追加来源记录，不能覆盖历史。deps.dev 使用数组索引，不按版本合并实例；错误字段进入 issues。版本选择先过滤 prerelease、dev release、全部文件已撤回或晚于 cutoff 的版本，再选择最新稳定版本及 2024、2025 每年的最早稳定版本，去重。

~~~python
def selected_release_names(releases: list[tuple[str, datetime]]) -> tuple[str, ...]:
    if not releases:
        return ()
    picks = [max(releases, key=lambda row: Version(row[0]))[0]]
    for year in (2024, 2025):
        candidates = [row for row in releases if row[1].year == year]
        if candidates:
            picks.append(min(candidates, key=lambda row: (row[1], Version(row[0])))[0])
    return tuple(dict.fromkeys(picks))
~~~

- [x] Step 4：验证多个相同 PackageVersion 实例、错误图、空版本年、future uploads、所有文件撤回、文件校验失败；HTTP 重试使用注入时钟，取消可中断等待；不下载或执行分发文件。
- [x] Step 5：提交 feat: preserve public dependency and source evidence。

~~~bash
git add backend/src/depscope/sources backend/src/depscope/ingest/depsdev.py backend/tests
git commit -m "feat: preserve public dependency and source evidence"
~~~

## Task 5: Neo4j 持久化、约束和幂等发布

**Files:** Create graph/{driver,migrations,snapshots}.py、runtime/pagination.py、migrations/001_core.cypher、tests/integration/test_snapshot_repository.py、compose.yaml 初始 Neo4j 服务。

**Interfaces:** Produces SnapshotRepository(driver)；create_project(name,kind="user_project") -> str；publish(snapshot: Snapshot,job_id: str) -> str；load(snapshot_id: str) -> Snapshot；delete_unpublished(job_id: str) -> int；list_snapshots(project_id,cursor=None,limit=50) -> Page。Page(items,next_cursor,observed_at) 定义在 runtime/pagination.py。

- [x] Step 1：创建仅绑定本机的 Neo4j 5.26 Compose 服务和持久卷，记录实际可拉取镜像摘要。使用测试项目 ID 命名空间清理集成测试，不能清空用户数据库。写失败测试。

~~~python
def test_duplicate_import_and_context_boundary(repo, public_snapshot_factory):
    project = repo.create_project("sample")
    snap = public_snapshot_factory(project)
    first = repo.publish(snap, "job-a")
    assert repo.publish(snap, "job-b") == first
    loaded = repo.load(first)
    assert len(loaded.edges) == 72
    assert all(e.from_id in {c.local_id for c in loaded.components} for e in loaded.edges)
~~~

- [x] Step 2：启动隔离测试数据库，运行 pytest tests/integration/test_snapshot_repository.py -q。数据库不可用属于未验证，不能以 skip 代替集成验收。
- [x] Step 3：建立唯一约束，分批写入 owner_job_id 标记的未发布快照，校验全部端点和数量后发布。已存在 ready 快照返回原 ID；失败只清理任务拥有的未发布实例与关系，保留共享 PackageVersion。

~~~cypher
CREATE CONSTRAINT snapshot_id IF NOT EXISTS
FOR (s:Snapshot) REQUIRE s.snapshot_id IS UNIQUE;
CREATE CONSTRAINT instance_key IF NOT EXISTS
FOR (c:ComponentInstance) REQUIRE (c.snapshot_id, c.local_id) IS UNIQUE;
MATCH (a:ComponentInstance {snapshot_id: $snapshot_id, local_id: $from_id})
MATCH (b:ComponentInstance {snapshot_id: $snapshot_id, local_id: $to_id})
MERGE (a)-[e:DEPENDS_ON]->(b)
SET e.requirement = $requirement, e.pointer = $pointer;
~~~

- [x] Step 4：验证同版本不同实例、两个快照的相同 local_id、写入中途异常、ready 不可变、幂等重试、删除范围和分页；迁移运行两次不改变结果。
- [x] Step 5：提交 feat: persist isolated snapshots in Neo4j。

~~~bash
git add backend/src/depscope/graph backend/src/depscope/runtime/pagination.py migrations compose.yaml backend/tests
git commit -m "feat: persist isolated snapshots in Neo4j"
~~~

## Task 6: 持久任务、取消和重启恢复

**Files:** Create jobs/{models,store,worker}.py、graph/jobs.py、tests/unit/test_job_transitions.py、tests/integration/test_worker_recovery.py。

**Interfaces:** Produces Job(id,kind,payload,status,phase,owner_token,progress,error,next_attempt_at)、JobStore.enqueue(kind,payload) -> Job、get(id) -> Job、claim(job_id,owner_token) -> bool、transition(id,expected,target) -> bool、request_cancel(id) -> None、mark_interrupted() -> int；Worker.run_once() -> bool。导入 handler 签名为 async handle_import(job: Job, cancelled: Callable[[],bool]) -> str；调用 Tasks 3—5。

- [x] Step 1：写失败测试。

~~~python
def test_restart_never_discards_published_snapshot(job_store, repo, ready_snapshot):
    job = job_store.enqueue("import", {"snapshot_id": ready_snapshot.snapshot_id})
    assert job_store.claim(job.id, "worker-old")
    job_store.mark_interrupted()
    assert repo.load(ready_snapshot.snapshot_id).snapshot_id == ready_snapshot.snapshot_id
    assert job_store.get(job.id).status == "interrupted"
~~~

- [x] Step 2：运行 pytest tests/unit/test_job_transitions.py tests/integration/test_worker_recovery.py -q。
- [x] Step 3：实现数据库原子 claim，锁定任务状态后判断条件；修改队列一次只持有一个全局 worker lease。取消检查位于网络等待、批次写入和发布前。允许的状态转换写为显式映射，重启将旧 lease 的非终态任务标为 interrupted，重试使用原导入身份。

~~~python
IMPORT_TRANSITIONS = {
    "queued": {"validating", "cancelled"},
    "validating": {"fetching", "writing", "failed", "cancelled"},
    "fetching": {"writing", "failed", "cancelled"},
    "writing": {"ready", "failed", "cancelled"},
    "interrupted": {"queued", "cancelled"},
}
~~~

- [x] Step 4：验证两个 worker 的竞争 claim、取消不删除 ready 数据、重试进度、不可重试错误及 429 等待中的取消；添加独立 worker 入口。
- [x] Step 5：提交 feat: add recoverable background jobs。

~~~bash
git add backend/src/depscope/jobs backend/src/depscope/graph/jobs.py backend/tests
git commit -m "feat: add recoverable background jobs"
~~~

## Task 7: OSV 查询、分页、公告全文与来源失败

**Files:** Create sources/osv.py、sources/advisories.py、tests/unit/test_osv.py、tests/unit/test_retry.py；Modify sources/retry.py，复用任务 4 的公共 HTTP 重试接口。

**Interfaces:** Produces PackageQuery(coordinate,status,record_ids,source_refs,issues)、OsvClient.query(coordinates: tuple[Coordinate,...]) -> tuple[PackageQuery,...]、OsvClient.advisory(id: str) -> AdvisoryRevision；AdvisoryRevision(id,modified,digest,aliases,related,withdrawn,affected,summary,details,source) 定义在 sources/advisories.py。

- [x] Step 1：以 respx 建立只有第二个查询分页的响应，写失败测试。

~~~python
async def test_pagination_tracks_each_coordinate(mock_osv, coordinates):
    mock_osv.batch([
        {"vulns": []},
        {"vulns": [{"id": "GHSA-a"}], "next_page_token": "page-two"},
    ])
    mock_osv.single_page("page-two", {"vulns": [{"id": "GHSA-b"}]})
    result = await mock_osv.client.query(coordinates[:2])
    assert result[0].status == "no_match"
    assert set(result[1].record_ids) == {"GHSA-a", "GHSA-b"}
    assert result[1].status == "matched"
~~~

- [x] Step 2：运行 pytest tests/unit/test_osv.py tests/unit/test_retry.py -q。
- [x] Step 3：按输入顺序关联 batch 结果，每批 100，并发 4；分页只继续相关条目。查询键包括生态、规范名、原始版本和采集批次；保存 POST 请求、响应及公告全文。测试夹具 mock_osv 在 tests/helpers/osv.py 定义 batch、single_page、client，通过 respx 截获真实 HTTP 请求。

~~~python
def merge_page(current: PackageQuery, page: dict) -> PackageQuery:
    ids = tuple(dict.fromkeys(current.record_ids + tuple(v["id"] for v in page.get("vulns", []))))
    status = "partial" if page.get("next_page_token") else ("matched" if ids else "no_match")
    return current.model_copy(update={"record_ids": ids, "status": status})
~~~

- [x] Step 4：验证分页中途失败保留 partial、批次数量不符返回 error、公告缺失不等于 no_match、撤回字段保留、HTTP 日期／秒数 Retry-After、认证失败不无限重试、日志认证值脱敏。
- [x] Step 5：提交 feat: query OSV with complete evidence and failure states。

~~~bash
git add backend/src/depscope/sources backend/tests
git commit -m "feat: query OSV with complete evidence and failure states"
~~~

## Task 8: 别名分组、Finding 和刷新运行

**Files:** Create analysis/{aliases,matching}.py、graph/match_runs.py、tests/unit/test_aliases.py、tests/integration/test_match_runs.py。

**Interfaces:** Consumes PackageQuery、AdvisoryRevision、SnapshotRepository。Produces alias_groups(records: tuple[AdvisoryRevision,...]) -> dict[str,tuple[str,...]]；MatchService.collect(snapshot_ids: tuple[str,...],collection_id: str) -> dict[str,MatchRun]；MatchRun(id,snapshot_id,collection_id,observed_at,queries,findings,revision_ids,coverage)；Finding(id,instance_id,group_id,revision_ids,status)。所有实例匹配使用 snapshot_id。

- [x] Step 1：写失败测试。

~~~python
def test_related_is_not_alias_and_withdrawn_is_not_active(advisory_factory):
    a = advisory_factory("GHSA-a", aliases=("CVE-1",), related=("GHSA-b",))
    b = advisory_factory("GHSA-b", aliases=())
    withdrawn = advisory_factory("GHSA-old", aliases=("CVE-1",), withdrawn="2026-01-01")
    groups = alias_groups((a, b, withdrawn))
    assert groups["GHSA-a"] != groups["GHSA-b"]
    assert "GHSA-old" not in groups
~~~

- [x] Step 2：运行 pytest tests/unit/test_aliases.py tests/integration/test_match_runs.py -q。
- [x] Step 3：对有效来源 ID 与 aliases 的连通集合分组，组键为排序标识列表的 SHA-256；related 不参与。affected 中包名／生态与查询坐标不相符的来源记 conflict。一个实例对应同组来源只产生一个 Finding，保留所有来源版本。

~~~python
def alias_group_key(identifiers: set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(identifiers)).encode()).hexdigest()

def confirmed_coverage(queries: tuple[PackageQuery, ...]) -> dict[str, int]:
    checked = sum(q.status in {"matched", "no_match"} for q in queries)
    return {"total": len(queries), "confirmed": checked, "unknown": len(queries) - checked}
~~~

- [x] Step 4：保存撤回记录但不产生有效 Finding；保留 raw matched 与有效匹配数的差别。验证旧运行不随新别名更改、共享 collection_id、坐标复用、只查询可靠坐标、所有 unknown／error 分母、历史运行选择。
- [x] Step 5：提交 feat: persist deduplicated findings and immutable match runs。

~~~bash
git add backend/src/depscope/analysis backend/src/depscope/graph/match_runs.py backend/tests
git commit -m "feat: persist deduplicated findings and immutable match runs"
~~~

## Task 9: 有界图浏览、路径与跨项目分析

**Files:** Create analysis/{paths,metrics,impact}.py、graph/queries.py、tests/unit/test_paths.py、tests/integration/test_impact.py。

**Interfaces:** Produces shortest_path(snapshot: Snapshot,target_id: str) -> tuple[str,...]|None；PathService.paths(finding_id: str,run_map: dict[str,str]) -> PathResult；PathResult(paths,total_reachable,display_nodes,hidden_nodes,completeness,run_map)；GraphService.view(snapshot_id,focus_id=None) -> GraphView。GraphView(snapshot_id,nodes,edges,total_nodes,hidden_nodes,completeness)；GraphNode(id,label,coordinate: Coordinate|None,query_status)、GraphEdge(source,target)。Finding.instance_id 和 GraphNode.id 使用 inst_key；服务先在所属 snapshot 下解析 local_id，再调用 BFS，返回图时转换回 inst_key。路径数据加载完整快照，再做 200 节点／20 路径的展示限制。

- [x] Step 1：写循环及跨快照失败测试。

~~~python
def test_cycle_terminates_without_cross_snapshot_path(snapshot_factory):
    a = snapshot_factory("a", ("r", "x", "y"), (("r","x"),("x","y"),("y","x")), root="r")
    b = snapshot_factory("b", ("x", "z"), (("x","z"),), root="x")
    assert shortest_path(a, "y") == ("r", "x", "y")
    assert shortest_path(a, "z") is None
    assert shortest_path(b, "z") == ("x", "z")
~~~

- [x] Step 2：运行 pytest tests/unit/test_paths.py tests/integration/test_impact.py -q。
- [x] Step 3：实现 BFS 并对缺失根直接返回未知路径，所有仓库路径查询带 snapshot_id。跨项目先匹配全局可靠坐标或来源标识，再分别加载各快照，不对混合图遍历。

~~~python
def shortest_path(snapshot: Snapshot, target_id: str) -> tuple[str, ...] | None:
    if snapshot.root_id is None:
        return None
    adjacency = defaultdict(list)
    for edge in snapshot.edges:
        adjacency[edge.from_id].append(edge.to_id)
    queue = deque([(snapshot.root_id, (snapshot.root_id,))])
    visited = {snapshot.root_id}
    while queue:
        node, path = queue.popleft()
        if node == target_id:
            return path
        for other in sorted(adjacency[node]):
            if other not in visited:
                visited.add(other)
                queue.append((other, path + (other,)))
    return None
~~~

- [x] Step 4：用 NetworkX 独立 oracle 核对构造图和两份真实图；验证大于 200 节点时聚合计数不缩小、未知依赖／缺失根不宣称完整、不同日期 run_map 明示。
- [x] Step 5：提交 feat: trace dependency paths and scoped project impact。

~~~bash
git add backend/src/depscope/analysis backend/src/depscope/graph/queries.py backend/tests
git commit -m "feat: trace dependency paths and scoped project impact"
~~~

## Task 10: 快照比较和验证等级

**Files:** Create analysis/{comparison,verification}.py、graph/comparisons.py、tests/unit/test_comparison.py、tests/integration/test_comparison_evidence.py。

**Interfaces:** Produces compare_packages(before: Snapshot,after: Snapshot) -> PackageDiff；PackageDiff(added,removed,versions_changed,opaque_before,opaque_after,environment_comparable)；compare_known_findings(before: MatchRun,after: MatchRun,before_snapshot: Snapshot,after_snapshot: Snapshot) -> MatchingDiff；MatchingDiff(removed_known_matches,unknown)。ComparisonService.create(before_id,after_id,verification_id: str|None) -> Comparison；VerificationRecord(kind,environment,source_hashes,command: tuple[str,...],exit_code: int|None,observed_at,result_digest,producer)；Comparison(id,baseline_id,candidate_id,run_ids,collection_id,diff,removed_known_matches,unknown,level,limitations)。verification_id 只定位本地验证流程已登记的资料，比较接口不接受用户提供的测试成功布尔值。

- [x] Step 1：写失败测试。

~~~python
def test_failed_query_cannot_be_counted_as_removed_match(comparison_inputs):
    before, after, before_snapshot, after_snapshot = comparison_inputs("matched", "error")
    result = compare_known_findings(before, after, before_snapshot, after_snapshot)
    assert result.removed_known_matches == 0
    assert result.unknown == 1
~~~

- [x] Step 2：运行 pytest tests/unit/test_comparison.py tests/integration/test_comparison_evidence.py -q。
- [x] Step 3：创建并集公告采集批次，固定两个 run_id；按包名和多版本集合比较。只有前后覆盖明确的组才计算已知匹配变化；任何缺失或冲突单列。

~~~python
def verification_level(resolution_ok: bool, tests_ok: bool,
                       environment_known: bool, constraints_complete: bool) -> str:
    if not resolution_ok or not environment_known or not constraints_complete:
        return "metadata_comparison"
    if tests_ok:
        return "tests_verified"
    return "resolution_verified"
~~~

- [x] Step 4：上段布尔量只由本地验证资料校验产生：分别验证 resolution 和 tests 记录、同环境、同候选依赖清单、完整解析、所有可确认约束、可信 producer 和文件校验；单纯上传 SBOM 或 JSON 里的 exit_code 不能升等级。比较已移除包时也需要候选图完整，版本变化按规范包名对应新版本集合。验证公告日期差异、无约束边、私有／opaque 组件、同名多个版本和历史比较不可变。
- [x] Step 5：提交 feat: compare upgrade evidence without overstating validation。

~~~bash
git add backend/src/depscope/analysis backend/src/depscope/graph/comparisons.py backend/tests
git commit -m "feat: compare upgrade evidence without overstating validation"
~~~

## Task 11: 核心 HTTP 接口与分页

**Files:** Create api/{dependencies,projects,imports,jobs,snapshots,findings,comparisons}.py；Modify runtime/app.py、runtime/pagination.py；Create tests/integration/test_core_api.py。

**Interfaces:** Produces build_services(settings: Settings) -> Services，Services 包含 repositories、worker、match_service、path_service、comparison_service。端点路径按规格第 9 节；列表响应 Page，写任务返回 job_id；增加 GET /api/projects、GET /api/projects/{id}/snapshots 和 POST /api/jobs/{id}/cancel 以支持界面操作。

- [x] Step 1：写失败测试。

~~~python
def test_streamed_oversize_import_has_no_published_snapshot(client, repo):
    project = client.post("/api/projects", json={"name": "demo"}).json()["id"]
    response = client.post("/api/projects/" + project + "/imports",
                           content=b"x" * (10 * 1024 * 1024 + 1),
                           headers={"Content-Type": "application/json", "Content-Length": "1"})
    assert response.status_code == 413
    assert repo.list_snapshots(project).items == ()
~~~

- [x] Step 2：运行 pytest tests/integration/test_core_api.py -q。
- [x] Step 3：导入端点接收 application/json 的文件原始字节，前端以 File 作为 body 发送；HTTP 层增量读取 Request.stream() 并计数，超过限制立即停止，异步版与 read_limited 使用相同规则，不依赖 Content-Length。归一错误转 422，超限 413，不存在 404，范围歧义 409，任务读取可重试错误包含码和位置。控制器只做校验和任务调度。

~~~python
def page_response(page: Page) -> dict:
    return {"items": [item.model_dump(mode="json") for item in page.items],
            "next_cursor": page.next_cursor, "observed_at": page.observed_at}
~~~

- [x] Step 4：验证多页读取、无效 cursor、任务取消、项目／快照 ID 不匹配、来源局部标识不可跨项目访问、服务重启后进度可读；OpenAPI 作为前端类型生成输入。
- [x] Step 5：提交 feat: expose core investigation APIs。

~~~bash
git add backend/src/depscope/api backend/src/depscope/runtime backend/tests
git commit -m "feat: expose core investigation APIs"
~~~

## Task 12: 可操作的图谱产品界面

**Files:** Create frontend/package.json、frontend/src/api/{client,types}.ts、features/{projects,graph,findings,comparisons}/、components/{CompletenessBadge,EvidenceLink,JobProgress}.tsx、frontend/tests/core-workflow.test.tsx、frontend/e2e/core-workflow.spec.ts。

**Interfaces:** API 类型由当前 OpenAPI 生成；fetchPage<T>(url,signal) -> Promise<Page<T>>；api.graph(id: string,signal?: AbortSignal) -> Promise<GraphView>；useSnapshot(snapshotId) -> {data,error,loading}。React 页面只使用当前选择的 snapshot_id 和 run_id；完整性与查询覆盖分别显示。

- [x] Step 1：建立 Node 22 构建配置，安装 React、Vite、TypeScript、Cytoscape.js、路由和测试依赖，写失败的切换测试。deferred() 在 frontend/tests/helpers.ts 返回 promise、resolve、reject。

~~~tsx
it("ignores a late response from the previous snapshot", async () => {
  const oldRequest = deferred<GraphView>();
  api.graph.mockImplementation((id) =>
    id === "old" ? oldRequest.promise : Promise.resolve(graphResponse("new", [])));
  const view = render(<GraphPage snapshotId="old" />);
  view.rerender(<GraphPage snapshotId="new" />);
  await waitFor(() => expect(screen.getByTestId("graph-scope")).toHaveAttribute("data-snapshot-id", "new"));
  await act(async () => oldRequest.resolve(graphResponse("old", ["stale-node"])));
  expect(screen.getByTestId("graph-scope")).toHaveAttribute("data-snapshot-id", "new");
});
~~~

- [x] Step 2：运行 npm test -- --run tests/core-workflow.test.tsx，确认失败。
- [x] Step 3：以 AbortController 和请求序号隔离异步结果；所有页面有加载、空数据、未知、来源失败和服务不可用状态。GraphPage 的 graph-scope 元素绑定实际数据的 snapshot_id，不能只绑定请求参数来掩盖陈旧数据。Cytoscape 只接收有界图，原始来源不完整时显示已观察范围。

~~~tsx
useEffect(() => {
  const controller = new AbortController();
  let current = true;
  api.graph(snapshotId, controller.signal).then((value) => {
    if (current && value.snapshot_id === snapshotId) setData(value);
  }).catch((error) => {
    if (current && error.name !== "AbortError") setError(error);
  });
  return () => { current = false; controller.abort(); };
}, [snapshotId]);
~~~

- [x] Step 4：实现创建项目、上传、任务进度、选择运行、搜索节点、路径查看和两快照比较；所有列表消费 next_cursor，摘要使用后端总量。验证 200 节点收起提示、未知项、不同公告日期、窄屏布局及键盘操作。
- [x] Step 5：在真实 Neo4j 和后端上运行 npm run build、npx playwright test e2e/core-workflow.spec.ts；保留页面截图与执行记录，不能把组件 mock 当成真实演示。
- [x] Step 6：提交 feat: ship the core dependency investigation interface。

~~~bash
git add frontend
git commit -m "feat: ship the core dependency investigation interface"
~~~

## Task 13: 证据索引、embedding 和四种检索

**Files:** Create retrieval/{documents,chunking,indexes,embedding,retrievers,rrf}.py、graph/evidence.py、investigation/models.py、tests/unit/test_retrieval.py、tests/integration/test_index_isolation.py。

**Interfaces:** Produces EvidenceDocument(id,text,source_ids,pointers,snapshot_id,run_id,entity_keys)、EvidenceChunk(evidence_id,document_id,text,start,end,source_ids)、IndexManifest(id,corpus_digest,model_id,model_digest,dimension,chunking_version)、EmbeddingBatch(vectors,model_id,model_digest,usage: dict|None)、SearchHit(evidence_id,index_id,score)；EmbeddingProvider.embed(texts: tuple[str,...]) -> EmbeddingBatch；IndexStore.write(manifest,evidence,vectors) -> None、search(manifest,vector) -> tuple[SearchHit,...]；Retriever.search(question: str,scope: InvestigationScope,method: str) -> tuple[EvidenceChunk,...]。InvestigationScope(project_ids,snapshot_ids,run_map,comparison_id: str|None) 在 investigation/models.py 定义。

- [x] Step 1：写同维度不同模型的失败测试。

~~~python
def test_equal_dimensions_do_not_mix_model_indexes(index_store, evidence):
    old = IndexManifest(id="a"*64, corpus_digest="c"*64, model_id="old", model_digest="1"*64, dimension=3, chunking_version="1")
    new = IndexManifest(id="b"*64, corpus_digest="c"*64, model_id="new", model_digest="2"*64, dimension=3, chunking_version="1")
    index_store.write(old, evidence, [[1., 0., 0.]])
    index_store.write(new, evidence, [[0., 1., 0.]])
    assert all(hit.index_id == new.id for hit in index_store.search(new, [0., 1., 0.]))
~~~

- [x] Step 2：运行 pytest tests/unit/test_retrieval.py tests/integration/test_index_isolation.py -q。
- [x] Step 3：按字段切分，文本字符位置以 Unicode code point 计；证据 ID 由来源 digest、pointer、start、end 生成。每个索引副本以 (evidence_id,index_id) 识别；向量和全文索引使用由 manifest SHA-256 生成的隔离标签，标签只能匹配固定十六进制格式。文档主体和来源不因 embedding 改变。

~~~python
def rrf(rankings: tuple[tuple[str, ...], ...], k: int = 60) -> tuple[str, ...]:
    scores = defaultdict(float)
    for ranking in rankings:
        for position, item in enumerate(dict.fromkeys(ranking), start=1):
            scores[item] += 1.0 / (k + position)
    return tuple(sorted(scores, key=lambda item: (-scores[item], item)))
~~~

- [x] Step 4：实现全文、向量、RRF、RRF 加当前快照关系扩展。精确标识定位对四种方法一致；最终统一去重和裁剪为 10 个片段、12,000 字符。测试 2,000／200 分片边界、零向量／NaN／维度错误、索引版本隔离、扩展不跨快照和截断记录。
- [x] Step 5：通过真实 Ollama embedding 和 Neo4j 索引做一次契约测试，记录模型摘要、维度和耗时；没有模型不能声称完成向量检索。
- [x] Step 6：提交 feat: add versioned evidence retrieval and graph expansion。

~~~bash
git add backend/src/depscope/retrieval backend/src/depscope/graph/evidence.py backend/src/depscope/investigation/models.py backend/tests
git commit -m "feat: add versioned evidence retrieval and graph expansion"
~~~

## Task 14: DeepSeek 生成与持久费用预留

**Files:** Create generation/{models,deepseek,budget,pricing}.py、graph/call_ledger.py、tests/unit/test_generation.py、tests/integration/test_call_ledger.py。

**Interfaces:** Produces Message(role,content)、GenerationResult(text,model_id,usage: dict|None,request_id: str|None)、GenerationProvider.generate(messages: tuple[Message,...],max_output: int) -> GenerationResult；BudgetPolicy(currency,max_amount: Decimal,max_calls: int)、Reservation(id,run_id,amount,status)、BudgetSummary(reserved,estimated_spent,call_count,remaining)；BudgetLedger.open_run(run_id,policy) -> None、reserve(run_id,amount: Decimal) -> Reservation、settle(id,usage: dict|None) -> None、summary(run_id) -> BudgetSummary；PriceProfile(provider,model,currency,observed_at,rates,source_uri)。

- [x] Step 1：写超时后重试的失败测试。

~~~python
def test_timeout_retains_reservation_and_retry_consumes_limit(ledger):
    policy = BudgetPolicy(currency="USD", max_amount=Decimal("0.10"), max_calls=1)
    ledger.open_run("r", policy)
    first = ledger.reserve("r", Decimal("0.03"))
    ledger.settle(first.id, None)
    assert ledger.summary("r").reserved == Decimal("0.03")
    with pytest.raises(DomainError, match="CALL_LIMIT"):
        ledger.reserve("r", Decimal("0.03"))
~~~

- [x] Step 2：运行 pytest tests/unit/test_generation.py tests/integration/test_call_ledger.py -q。
- [x] Step 3：使用 httpx 构造 DeepSeek 非思考请求，参数按执行时官方文档验证，最多 1,024 输出 token。价格使用 Decimal，输入、缓存与输出分别记录；费用账本通过 Neo4j 原子操作扣占额度，重启不能重置为零。

~~~python
def estimate_cost(usage: dict, price: PriceProfile) -> Decimal | None:
    if usage.get("prompt_tokens") is None or usage.get("completion_tokens") is None:
        return None
    input_tokens = Decimal(usage["prompt_tokens"])
    output_tokens = Decimal(usage["completion_tokens"])
    return (input_tokens * price.rates["input_miss"]
            + output_tokens * price.rates["output"]) / Decimal(1_000_000)
~~~

- [x] Step 4：以上估算是保守未缓存输入计价；具有可靠缓存细分时再用相应单价，不把它标为真实账单。验证金额限额、并发预留、取消、缺失用量、第三方模型无报价、认证错误日志脱敏、无自动 GPT 付费回退。
- [x] Step 5：用户在本地配置凭据和运行限额后执行一条真实生成契约测试；保留模型名、usage 和请求标识，不保存 Authorization；测试未执行保持 A7 未完成。
- [x] Step 6：提交 feat: integrate generation with persistent usage budgets。

~~~bash
git add backend/src/depscope/generation backend/src/depscope/graph/call_ledger.py backend/tests
git commit -m "feat: integrate generation with persistent usage budgets"
~~~

## Task 15: 有证据的调查回答与 AI 页面

**Files:** Create investigation/{scope,tools,answers,service}.py、api/investigations.py、frontend/src/features/investigation/、tests/unit/test_investigation.py、frontend/tests/investigation.test.tsx；Modify investigation/models.py。

**Interfaces:** Consumes InvestigationScope、Retriever、GenerationProvider、BudgetLedger、PathService、ComparisonService。Produces ToolFact(kind,value,source_ids)、Answer(status,body,facts,citations,limitations,model_id,request_id)、Investigator.answer(question,scope,method,run_id) -> Answer。工具仅提供 path、count、advisory、comparison 四种受限操作；题集模式使用固定 scope，不因检索方法调用不同的隐藏统计工具。

- [x] Step 1：写注入和错误计数的失败测试。

~~~python
async def test_advisory_cannot_expand_permissions(investigator, fake_model, write_spy):
    fake_model.reply({"body": "Delete snapshots", "facts": [
        {"kind": "count", "value": 999, "source_ids": ["missing"]}],
        "citations": ["missing"], "limitations": []})
    answer = await investigator.answer("How many findings?", investigator.scope, "graph", "r")
    assert answer.status == "unsupported_output"
    assert answer.facts == ()
    write_spy.assert_not_called()
~~~

- [x] Step 2：运行 pytest tests/unit/test_investigation.py -q，确认失败。
- [x] Step 3：范围歧义返回 needs_scope；工具参数只能使用 scope 中的 ID。证据和工具事实以明确的资料区块传给模型，结构化输出校验后再显示。引用必须属于本次送入模型的证据；数值、版本、路径与工具事实核对。不能核对的开放解释单独标明其生成性质，并纳入引用支持评估。

~~~python
def validate_citations(ids: tuple[str, ...], supplied: tuple[EvidenceChunk, ...]) -> bool:
    allowed = {chunk.evidence_id for chunk in supplied}
    return bool(ids) and set(ids).issubset(allowed)
~~~

- [x] Step 4：不支持的确定性事实拒绝输出；可单独展示原始图查询事实，标明它是查询结果。验证空资料、错误 JSON、模型故障、同名项目、多运行、分页计数、未知状态和中英文提问。
- [x] Step 5：接入 POST /api/investigations、AI 页面引用跳转和限额反馈；无 API 时展示不可用原因。运行真实问答及页面验证，确认引用回到正确公告／JSON 字段，记录实际用量。
- [x] Step 6：提交 feat: answer scoped investigations with source evidence。

~~~bash
git add backend/src/depscope/investigation backend/src/depscope/api/investigations.py frontend/src/features/investigation frontend/tests/investigation.test.tsx backend/tests
git commit -m "feat: answer scoped investigations with source evidence"
~~~

## Task 16: 公开语料和两份实际环境 SBOM

**Files:** Create evaluation/{corpus,selection}.py、cli.py、examples/evidence_assistant/{pyproject.toml,assistant.py,tests/test_assistant.py}、tests/unit/test_corpus.py、artifacts/corpus/、docs/architecture/source_dictionary.md。

**Interfaces:** Produces CorpusCollector.collect(packages: tuple[str,...],cutoff: datetime) -> CorpusManifest；CorpusManifest(id,cutoff,case_ids,source_hashes,exclusions,actual_counts)；案例包含 family_name、snapshot_id、run_id、source_kind 和资料日期。CLI 子命令为 collect-corpus、import-file、match、export-verification，业务调用前述服务。ExampleAssistant.summarize(evidence: dict[str,str]) -> Answer 复用 GenerationProvider 与引用验证；VerificationRegistry.register(report_path,project_id,snapshot_id) -> str 只登记本地允许的验证 producer 输出。

- [ ] Step 1：写失败测试，确认版本年不存在不以性能结果补选。

~~~python
async def test_corpus_preserves_selection_failures(corpus_factory):
    manifest = await corpus_factory(missing_year=("langgraph", 2024), resolution_error=("mlflow", "candidate"))
    assert any(row["reason"] == "missing_year" for row in manifest.exclusions)
    assert any(row["reason"] == "resolution_error" for row in manifest.exclusions)
    assert manifest.actual_counts["successful_snapshots"] < 45
~~~

- [ ] Step 2：运行 pytest tests/unit/test_corpus.py -q。
- [ ] Step 3：采集规格列出的 15 个包，保存 PyPI metadata、版本选择和全部解析失败；所有资料冻结到本次清单。实际采集命令如下，数据范围取显式截止时间，不调用旧包代码。

~~~bash
.venv/bin/python -m depscope.cli collect-corpus --cutoff 2026-10-13T23:59:59-05:00 --output ../artifacts/corpus
~~~

- [ ] Step 4：示例应用是读取用户选择的公开证据文件并调用 GenerationProvider 生成带引用解释的 CLI；输入参数只接受本地路径和已配置服务。建立自己的 pyproject 和锁定依赖，使用响应夹具测试引用及错误传播，再做一条真实 API 调用。

~~~python
async def test_example_preserves_evidence_ids(example_assistant, fake_model):
    fake_model.reply({"body": "Summary", "citations": ["record-a"]})
    answer = await example_assistant.summarize({"record-a": "Public advisory text"})
    assert answer.citations == ("record-a",)
~~~

- [ ] Step 5：建立 backend 的运行环境及示例应用独立环境，保存安装清单、Python／平台、锁文件、测试退出码和原始 SBOM。CycloneDX 工具使用单独工具环境，按其实际 CLI help 确认 interpreter 和 pyproject 参数。

~~~bash
cyclonedx-py environment .venv-runtime/bin/python --pyproject pyproject.toml --spec-version 1.6 --output-format JSON --output-reproducible --output-file ../artifacts/corpus/backend-environment.cdx.json
~~~

- [ ] Step 6：从 examples/evidence_assistant 目录采集示例环境，再从 backend 目录调用 import-file 导入两份 SBOM，标记 observed_environment。验证实际依赖边是否完整，不能仅因生成工具退出 0 就标为完整图。

~~~bash
cyclonedx-py environment .venv-runtime/bin/python --pyproject pyproject.toml --spec-version 1.6 --output-format JSON --output-reproducible --output-file ../../artifacts/corpus/example-environment.cdx.json
~~~
- [ ] Step 7：提交 data: freeze public cases and observed environment evidence；私有文件保留在被忽略的本地目录。

~~~bash
git add backend/src/depscope/evaluation backend/src/depscope/cli.py examples artifacts/corpus docs/architecture backend/tests
git commit -m "data: freeze public cases and observed environment evidence"
~~~

## Task 17: 200 题、冻结评估及实验页面

**Files:** Create evaluation/{benchmark,reference,freeze,runner,metrics,report}.py、api/experiments.py、frontend/src/features/experiments/、tests/unit/test_benchmark.py、tests/unit/test_metrics.py、artifacts/benchmark/、docs/evaluation/protocol.md。

**Interfaces:** Produces Question(id,kind,split,family_names,scope,prompt,source_ids,expected_facts,required_evidence,label_origin,review_status)、build_benchmark(manifest: CorpusManifest) -> tuple[Question,...]、freeze_suite(questions,config,output: Path) -> FrozenSuite、ExperimentRunner.run(suite,methods,run_id) -> ExperimentManifest。FrozenSuite(digest,question_digest,corpus_digest,config_digest,output_path)；ExperimentManifest(id,suite_digest,method_results,usage,cost,failures)。reference.py 只读原始证据并使用独立 NetworkX 图，不调用产品的 paths／matching 实现产生答案。

- [ ] Step 1：写失败测试。

~~~python
def test_frozen_benchmark_has_no_family_leakage(benchmark):
    dev = [q for q in benchmark if q.split == "dev"]
    test = [q for q in benchmark if q.split == "test"]
    assert len(dev) == 60 and len(test) == 140
    assert set().union(*(set(q.family_names) for q in dev)).isdisjoint(
        set().union(*(set(q.family_names) for q in test)))
    assert all(q.source_ids and q.label_origin for q in benchmark)
~~~

- [ ] Step 2：运行 pytest tests/unit/test_benchmark.py tests/unit/test_metrics.py -q。
- [ ] Step 3：以原始公开资料构造五类案例，配额严格按规格；按 family hash 分组，题目与证据组合去重。只有实际证据能支撑的题可进入；资料不足时停止并记录缺口，不能用虚构公告或人造图补齐主要题集。标准标签默认 program_reference，真实人工审核才改变 review_status。

~~~python
def family_split(family_name: str, all_families: tuple[str, ...]) -> str:
    ordered = sorted(all_families,
        key=lambda name: hashlib.sha256(("20261013:" + name).encode()).hexdigest())
    return "dev" if family_name in ordered[:3] else "test"

def evidence_recall(required: set[str], retrieved: set[str]) -> float | None:
    return len(required & retrieved) / len(required) if required else None
~~~

- [ ] Step 4：固定开发题调参，冻结全部资料、200 题、模型、提示、切分、检索和价格配置的校验值。开发题至少有一次四方法的完整运行，共 240 次；冻结测试题四种方法共 560 次最终回答。两者至少共 800 次生成，重试另计；在批量金额和调用数上限明确后运行。方法顺序按固定种子交错，保留失败和断点，不只记录成功请求。
- [ ] Step 5：输出题型结果、逐题差值、家族 bootstrap、引用定位与支持分开、正确拒答与服务失败分开、真实 token／估算费用；没有开放解释审核时不输出虚假的语义准确率。跨项目题以排序后的 family_names 组合为案例家族分组，保存实际分组数；组合间仍可能共享家族，因此区间作为描述性稳定性分析，不声称完全独立或作总体显著性结论。独立组少时注明区间不稳定。
- [ ] Step 6：实验页面只展示有 run_id 的真实运行；增加 GET /api/experiments 列表及 GET /api/experiments/{id}。校验冻结后拒绝无记录改题／改配置，软件缺陷复评有变更记录。
- [ ] Step 7：提交 eval: add frozen benchmark and reproducible retrieval comparison。

~~~bash
git add backend/src/depscope/evaluation backend/src/depscope/api/experiments.py frontend/src/features/experiments artifacts/benchmark artifacts/experiments docs/evaluation backend/tests
git commit -m "eval: add frozen benchmark and reproducible retrieval comparison"
~~~

## Task 18: 容器、清洁复现、演示和简历材料

**Files:** Create backend/Dockerfile、frontend/Dockerfile、frontend/nginx.conf、.github/workflows/ci.yml、scripts/verify_release.py、docs/operations/{setup,backup,verification}.md、README.md、README.zh-CN.md、docs/portfolio/{demo_script,resume_evidence}.md、frontend/e2e/full-workflow.spec.ts；Modify compose.yaml，完成其全部服务配置。

**Interfaces:** Produces ReleaseManifest(commit,dependencies,images,source_manifest,verification_runs,experiment_runs,limitations)、verify_release(root: Path) -> ReleaseManifest。验证器检查实际文件及结果签名，不执行用户上传资料中的命令。CLI 增加 backup(output: Path) 和 restore(input: Path,new_instance: bool)；备份属于私有本地资料，包含一致的图导出、原始证据索引及费用账本，恢复必须校验 digest 并明确目标实例。

- [ ] Step 1：写完整业务流程失败测试：启动、导入、任务进度、路径、候选比较、真实问答、实验读取；外部服务缺失时流程明确区分核心服务可用与 AI 尚未验证。

~~~typescript
test("shows scoped evidence through the complete product", async ({page}) => {
  await page.goto("/");
  await page.getByRole("button", {name: "Load verified public sample"}).click();
  await expect(page.getByText("langchain-community")).toBeVisible();
  await page.getByRole("link", {name: "Impact paths"}).click();
  await expect(page.getByText("langchain-experimental")).toBeVisible();
  await expect(page.getByText("Observed dependency evidence")).toBeVisible();
});
~~~

- [ ] Step 2：运行 npx playwright test e2e/full-workflow.spec.ts；检查失败与实际功能缺口。
- [ ] Step 3：完成 Compose 的 Neo4j、API、worker 和前端；embedding 提供可选内部 Ollama 服务 profile，避免宿主回环地址在容器中含义不同。所有发布端口绑定 127.0.0.1，原始资料、数据库、模型和账本持久化；启动不偷偷调用付费生成。

~~~yaml
services:
  neo4j:
    image: neo4j:5.26
    ports:
      - "127.0.0.1:7474:7474"
      - "127.0.0.1:7687:7687"
  ollama:
    profiles: ["embeddings"]
    image: ollama/ollama
    volumes:
      - ollama_models:/root/.ollama
volumes:
  ollama_models:
~~~

- [ ] Step 4：以上服务片段在执行时补入经过验证的环境、持久卷、健康检查及精确镜像摘要；执行清洁重建，不能删除用户已有卷。模型下载通过明确的初始化命令进行，记录 Qwen 模型摘要。验证仅恢复图／资料也能浏览历史结果，费用账本不能被备份遗漏。
- [ ] Step 5：CI 使用真实 Neo4j 服务执行后端集成测试，使用离线来源夹具运行普通测试；付费 API 测试单独标记，仅有明确凭据和限额时运行。后端、前端和容器的依赖版本锁定为实际通过版本。
- [ ] Step 6：运行下面最终检查，保存退出码、日志校验值和 commit；检查 API 可用、来源追踪、真实问答、全部实验和 A1—A10，未通过的项目单独列出。第一块在 backend，第二块在 frontend，第三块在仓库根目录执行。

~~~bash
.venv/bin/python -m pytest tests/unit tests/integration -q
~~~

~~~bash
npm run build
npx playwright test e2e/full-workflow.spec.ts
~~~

~~~bash
docker compose build
docker compose up -d
backend/.venv/bin/python scripts/verify_release.py
~~~

- [ ] Step 7：脚本按其路径从仓库根运行；backend 与 frontend 命令在各自目录运行。录制真实产品演示，双语 README 说明安装、导入、费用设置、数据刷新、证据等级、评估及已知局限。
- [ ] Step 8：resume_evidence 中每个数量与性能指标链接到实际清单或实验结果，描述作者完成的内容及核验程度；没有用户和业务效果数据时不填相关数字。仓库在没有真实远程发布之前只称本地仓库，准备好交付包再处理远程发布。
- [ ] Step 9：提交 chore: package verified DepScope release and portfolio evidence。

~~~bash
git add backend/Dockerfile frontend/Dockerfile frontend/nginx.conf frontend/e2e/full-workflow.spec.ts compose.yaml .github scripts docs/operations docs/portfolio README.md README.zh-CN.md
git commit -m "chore: package verified DepScope release and portfolio evidence"
~~~

## 覆盖映射与执行交接

| 规格要求 | 任务 |
|---|---|
| 场景、范围、两类来源与真实性 | 1、4、12、16、18 |
| 导入、身份、根、未知语义、上限 | 2、3、4、11 |
| Neo4j 图模型、快照隔离、幂等 | 5、6、8、9、13 |
| 公告分页、别名、撤回、失败及覆盖 | 7、8 |
| 路径、跨项目、聚合与有界显示 | 9、11、12 |
| 同批资料比较、约束与验证等级 | 8、10、16 |
| API、embedding、证据、引用及费用 | 13、14、15 |
| 所有产品页面与分页、错误、恢复 | 6、11、12、15、17 |
| 固定资料、200 题、60／140、四方法 | 16、17 |
| 部署、清洁复现、实际成果及简历 | 18 |
| A1／A2／A3 | 5、6、9、11、18 |
| A4／A5／A6 | 7、8、10、16 |
| A7／A8／A9／A10 | 14、15、17、18 |

实施时先确认规格和计划无修改，并选择直接执行或逐任务子代理执行。推荐当前会话直接执行：18 项任务依赖同一套快照、身份与证据接口，连续开发能减少反复加载上下文；完成后进行一次独立整体验收。使用子代理方式则每项任务有独立实现和审查，成本更高。

每项任务完成后更新其复测、运行证据及提交记录，检查下一任务依赖；因真实来源或模型接口变化产生的范围修订写入变更记录。只有实际实现、验证和完成评估后，才能将本项目标记为完成。


### 实施时使用的官方参考

- [PyPI JSON API](https://docs.pypi.org/api/json/)：版本及分发文件发布时间。
- [CycloneDX Python CLI](https://github.com/CycloneDX/cyclonedx-python/blob/main/docs/usage.rst)：实际环境、pyproject 与 1.6 导出参数。
- [Neo4j 5 向量索引](https://neo4j.com/docs/cypher-manual/5/indexes/search-indexes/vector-indexes/)：版本化向量索引的创建及查询。
- DeepSeek 的模型、计价和模式参数以规格列出的官方文档为准，执行真实调用前重新核验。
