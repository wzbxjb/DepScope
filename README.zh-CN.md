# DepScope：AI 应用依赖风险调查平台

用 **Neo4j 知识图谱（Knowledge Graph）+ AI**，帮助开发者回答：应用依赖了什么、公告影响经由哪条间接依赖传入、两个版本快照有哪些变化，以及目前的证据能支持什么结论。

项目包含完整界面、后端、真实公开数据采集、两份实际环境 SBOM、检索对照评估和交付检查。界面为英文，便于演示和英文求职。它不会自动修改依赖，也不会把“没有已知公告”解释为安全。

[English](README.md) · [安装](docs/operations/setup.md) · [真实实验结果](docs/evaluation/results.md) · [来源字典](docs/architecture/source_dictionary.md) · [演示脚本](docs/portfolio/demo_script.md)

![实际界面](artifacts/verification/core-desktop.png)

## 启动

在本仓库根目录执行：

```sh
cp .env.example .env
# 填写自己的 Neo4j 密码；只浏览核心功能不需要模型 API。
export DEPSCOPE_LOCAL_UID=$(id -u)
docker compose build
docker compose up -d --wait
```

打开 **http://127.0.0.1:8080**；API 文档为 http://127.0.0.1:8101/docs。所有发布端口仅绑定本机。保留 `.env`、`data/runtime` 和 `artifacts/private` 的私密性；数据库、原始证据、签名记录和费用账本都持久化。启动不会自动调用付费模型或下载模型。

首次可点“Load verified public sample”，或创建项目上传 CycloneDX 1.6 JSON。每份快照、公告查询都有独立上下文和日期；失败、缺失根、未知依赖及不可靠坐标都有明确状态。比较页中的“metadata comparison”只代表资料对比，不能证明安装或升级兼容。

AI 使用用户配置的 DeepSeek API，本地 Qwen 提供 embedding（向量表示）。需显式设置调用和费用限额；重启不会清空历史费用。GPT 的服务地址和具体模型尚未提供，因此没有自动付费回退。详细步骤见[安装说明](docs/operations/setup.md)。

## 实际完成的数据和实验

- 公开语料：15 个根包、45 份完整公开依赖解析快照、10 个包家族、30 组比较。它们不是 45 个企业项目，也不代表历史安装环境。
- 实际环境：本项目后端和独立 AI 示例应用，各有原始 SBOM、独立核对的依赖边、安装检查和真实测试记录。自环境验证不等于验证升级。
- 评估：200 题，开发集 60 / 测试集 140，四种检索策略，共 800 次真实生成调用，所有失败和拒答都保留。标签由独立程序及原始资料生成，没有冒充人工金标准。
- 测试集的 126 道事实题：全文检索准确率 24.6%，向量 37.3%，混合 39.7%，混合加图扩展 38.1%。图扩展没有超过混合方案，原样报告。
- 本轮记录输入 5,212,843 / 输出 246,258 token；按冻结峰值价格估算上限约 1.64 美元，并非供应商账单。

[结果报告](docs/evaluation/results.md)说明了分母、14 道缺失证据题的拒答表现、题型差异、耗时和区间局限。测试只有 7 个底层家族，组合分组互相重叠，不能据此声称总体显著性。引用能定位，不代表解释语义已经得到人工确认。

## 工程与交付

实现了快照隔离、实例与版本分离、公告别名去重、最短影响路径、来源追溯、四类检索、答案校验、费用预留及持久化、后台任务、容器运行和独立测试数据库。自动化检查覆盖核心边界；付费问答另有显式开关。

[备份恢复说明](docs/operations/backup.md)解释了如何保留图、原始证据和费用账本，并只恢复到全新实例。[最终验收](docs/operations/verification.md)依据真实日志、签名和摘要，不把缺失记录算通过。

目前是**本地仓库**。没有虚构用户、企业部署、收入或业务收益，也尚未发布到 GitHub。[简历证据表](docs/portfolio/resume_evidence.md)只使用可回查的功能和实际数字。
