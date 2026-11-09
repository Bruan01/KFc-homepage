/* LRobotcup · 具身智能入行专题
   ------------------------------------------------------------------
   纯 vanilla JS，无外部依赖。数据全部来自 2026-11-05 的公开资料调研，
   与 output/embodied-ai-research.md 一一对应。
   约定：
   - 发帖统一走 /forum?compose=1，模板通过 sessionStorage 传给论坛编辑器；
   - 动态内容一律用 textContent / createElement，不拼 innerHTML；
   - 外链只使用 https，且带 noopener noreferrer。
*/
(() => {
  "use strict";

  const PROGRESS_KEY = "kflow:lrc-progress";
  const TRACK_KEY = "kflow:lrc-track";
  const COMPOSE_SEED_KEY = "kflow:compose-seed";
  const COMPOSE_URL = "/forum?compose=1";
  const CHECKIN_TAG = "#具身智能打卡";
  // 多取一些再按相关性过滤，避免通用信源的无关条目把首屏占满。
  const NEWS_API = "/api/feeds/items?source_category=embodied-ai&limit=60";

  // 调研产物由 lrobotcup-data.js 提供（本页引用它，pages.py 会自动加 ?v=）。
  const DATA = window.KFLOW_LRC_DATA || {};
  const NEWS_SEED = (DATA.news && DATA.news.items) || [];
  const NEWS_SOURCES = (DATA.news && DATA.news.sources) || [];
  const HARDWARE = (DATA.hardware && DATA.hardware.items) || [];
  const CAREER = DATA.career || {};
  const TRACKS = CAREER.tracks || [];

  const ROLES = [
    {
      name: "VLA / 具身大模型算法",
      duty: "端到端多模态具身大模型研发；跨本体预训练、微调与部署；动作 token 化。",
      skills: "硕士+；Python / PyTorch；深入理解 Transformer；VLM / VLA / 世界模型；扩散模型与流匹配；大模型预训练、微调与分布式训练（FSDP / Deepspeed）。",
      keywords: ["VLA", "VLM", "OpenVLA", "π0", "GR00T", "World Model", "Action Token", "LoRA", "FSDP"],
    },
    {
      name: "机器人控制 / 运控（小脑）",
      duty: "人形与四足全身运动控制（WBC）、力控与柔顺控制、灵巧操作。",
      skills: "运动学与动力学、ROS / ROS2、RL / IL 策略训练、阻抗与导纳控制、MPC。",
      keywords: ["WBC", "PPO/SAC", "Sim2Real", "MPC", "阻抗控制", "力控"],
    },
    {
      name: "强化学习 / 模仿学习算法",
      duty: "操作任务的 RL 策略、真机强化学习、离线 RL。",
      skills: "PPO / SAC / BC / DAgger / 离线 RL；仿真或真机训练经验；奖励曲线分析。",
      keywords: ["PPO", "SAC", "Behavior Cloning", "DAgger", "Offline RL", "HIL-SERL"],
    },
    {
      name: "仿真与数据 / Sim2Real",
      duty: "仿真环境搭建、合成数据生成、数字孪生、系统辨识。",
      skills: "Isaac Sim / Isaac Lab / MuJoCo / Gazebo / SAPIEN；刚体动力学；执行器建模；域随机化。",
      keywords: ["Isaac Sim", "Isaac Lab", "MuJoCo", "Domain Randomization", "System ID"],
    },
    {
      name: "部署 / 工程化 / 机器人系统",
      duty: "模型量化、推理加速、嵌入式部署、系统联调。",
      skills: "C++ / Linux / Python；ONNX / TensorRT；INT8/INT4 量化；ROS2 中间件、runtime、实时通信。",
      keywords: ["C++", "Linux", "ROS2", "TensorRT", "ONNX", "EtherCAT", "嵌入式"],
    },
    {
      name: "SLAM / 感知 / 3D 视觉",
      duty: "定位建图、6D 位姿估计、点云处理、多传感器融合。",
      skills: "3D 视觉、点云滤波与配准、PnP / EPnP、LiDAR、多传感器融合、手眼标定。",
      keywords: ["SLAM", "6D Pose", "Point Cloud", "多传感器融合", "手眼标定"],
    },
  ];

  const LEVEL_LABEL = { starter: "零硬件起步", core: "核心复现", advanced: "进阶 / 真机" };

  const PROJECTS = [
    {
      level: "starter",
      name: "LeRobot Push-T：第一条闭环",
      desc: "下载 lerobot/pusht 演示 → 训练 Diffusion Policy → eval_policy 可视化。全程纯仿真，不需要机械臂。",
      hardware: "零硬件，CPU 或 Colab 即可",
      output: "一张训练曲线 + 一段评估可视化 + 一份复现 README",
      link: "https://github.com/huggingface/lerobot",
    },
    {
      level: "starter",
      name: "Gymnasium + SB3 奖励曲线",
      desc: "用 Stable-Baselines3 训练 PPO / SAC，画出奖励曲线并解释震荡与收敛，建立 RL 的基本直觉。",
      hardware: "零硬件",
      output: "两张奖励曲线 + 超参对照表",
      link: "https://stable-baselines3.readthedocs.io/",
    },
    {
      level: "starter",
      name: "社区数据集可视化与清洗",
      desc: "在 LeRobot Hub 挑 3 个数据集，读懂字段、可视化 episode、写一份数据字典；门槛低但极易出成果。",
      hardware: "零硬件",
      output: "数据字典 + 可视化截图 + 字段口径说明",
      link: "https://huggingface.co/lerobot",
    },
    {
      level: "core",
      name: "ACT / ALOHA 经典复现",
      desc: "中文社区公认的经典入门项目：理解 CVAE 与 action chunk，跑通训练 → 测试 → 推理全流程。",
      hardware: "单 GPU；有 ALOHA 硬件更佳，也可先在仿真复现",
      output: "成功率统计 + 失败案例分析",
      link: "https://github.com/tonyzhaozh/act",
    },
    {
      level: "core",
      name: "Diffusion Policy 复现与微调",
      desc: "理解「生成式策略」的核心项目。论文指出 50–150 条演示即可训练出效果，适合感受数据量的影响。",
      hardware: "单 GPU",
      output: "不同演示条数下的成功率对比",
      link: "https://github.com/real-stanford/diffusion_policy",
    },
    {
      level: "core",
      name: "ROS2 + MoveIt2 仿真抓取",
      desc: "正逆解 + 轨迹规划 + 抓取闭环，接入 Gazebo。算法侧补机器人学的最短路径。",
      hardware: "CPU 即可（Gazebo / MoveIt2）",
      output: "可复现的抓取 demo + TF 树说明",
      link: "https://docs.ros.org/",
    },
    {
      level: "core",
      name: "OXE / LIBERO 数据管线",
      desc: "读懂 → 清洗 → 转换 → 可视化 → 生成可训练格式。最接近「数据与仿真」岗位的日常，也最容易被忽略。",
      hardware: "零硬件到单 GPU",
      output: "一个可复用的数据转换脚本 + 规模口径说明",
      link: "https://github.com/google-deepmind/open_x_embodiment",
    },
    {
      level: "advanced",
      name: "SmolVLA / OpenVLA-OFT 微调",
      desc: "数据准备 → LoRA 微调 → 推理 → 部署，最贴近一线 VLA 工作流。避开 7B 全量训练，先跑 450M 级模型。",
      hardware: "消费级单卡（≥12GB 显存更稳）",
      output: "微调前后 LIBERO 成功率对比 + 推理延迟记录",
      link: "https://openvla-oft.github.io/",
    },
    {
      level: "advanced",
      name: "Isaac Sim 域随机化 Sim2Real",
      desc: "搭场景 → 视觉/物理参数随机化训练 → 记录 sim 与 real 成功率差。注意 Isaac Sim 与 Isaac Lab 严格版本配对。",
      hardware: "必须 RTX 显卡",
      output: "sim/real gap 报告 + 三类 gap 来源分析",
      link: "https://isaac-sim.github.io/IsaacLab/main/",
    },
    {
      level: "advanced",
      name: "SO-101 采集 → 补数据 → 重训",
      desc: "采 50 条演示训 ACT，记录首次成功率；再补 50 条覆盖失败案例，重训对比。这个前后数字本身就是作品集。",
      hardware: "SO-101 双臂 + 2 个不同型号摄像头",
      output: "带基线对比、失败分析与种子记录的端到端报告",
      link: "https://huggingface.co/docs/lerobot/so101",
    },
  ];

  const RESOURCES = [
    { kind: "course", name: "CS 285 · Deep Reinforcement Learning", desc: "UC Berkeley，2026 春季在授（Sergey Levine）。25 讲含 BC、策略梯度、SAC、离线 RL；作业公开。", url: "https://rail.eecs.berkeley.edu/deeprlcourse/", verified: true },
    { kind: "course", name: "Spinning Up in Deep RL", desc: "OpenAI 官方 RL 入门，含 VPG / TRPO / PPO / DDPG / TD3 / SAC 理论、实现与关键论文清单。", url: "https://spinningup.openai.com/en/latest/", verified: true },
    { kind: "course", name: "Hugging Face Robotics Course", desc: "免费、明确「无需硬件」，纯仿真 + 公开数据集，约 30–45 分钟一个单元。零成本第一站。", url: "https://huggingface.co/learn/robotics-course/unit0/1" },
    { kind: "course", name: "Modern Robotics 专项课（6 门）", desc: "Northwestern / Coursera：运动基础、运动学、动力学、规划与控制、操作与轮式机器人、Capstone。", url: "https://lynchandpark.org/", verified: true },
    { kind: "course", name: "Dive into Embodied AI 学习路径", desc: "DataWhale：基础 1–2 月 / 定向 2–3 月 / 项目持续，含 6 个项目，中文结构化程度最高。", url: "https://datawhalechina.github.io/dive-into-embodied-ai/docs/overview/learning-path", verified: true },
    { kind: "course", name: "Xbotics 具身智能手册（19 讲）", desc: "从端到端、数据采集、模仿学习、Diffusion Policy、VLA 实操到 RL / VLN，附全部开源链接。", url: "https://github.com/Xbotics-Embodied-AI-club/Xbotics-Embodied-AI-Handbook" },
    { kind: "course", name: "李宏毅机器学习 / 生成模型", desc: "台大课程主页，中文学习路线常引用的补课材料。", url: "https://speech.ee.ntu.edu.tw/hylee/index.php" },
    { kind: "book", name: "Modern Robotics: Mechanics, Planning, and Control", desc: "Lynch & Park，免费 PDF 预印本 + 视频 + 习题。旋量理论 / 指数坐标，研究生阶段主力教材。", url: "https://lynchandpark.org/", verified: true },
    { kind: "book", name: "Reinforcement Learning: An Introduction (2nd ed.)", desc: "Sutton & Barto，免费 PDF；理论圣经，配合 CS285 与 Spinning Up 读。", url: "http://incompleteideas.net/book/the-book-2nd.html" },
    { kind: "book", name: "Probabilistic Robotics", desc: "Thrun / Burgard / Fox，SLAM 与概率感知，数学最密，适合 L1 进阶选读。", url: "" },
    { kind: "book", name: "Craig / Siciliano / Mataric 系列", desc: "本科用 Craig 或 Niku 打运动学基础，The Robotics Primer 适合完全零基础。", url: "" },
    { kind: "paper", name: "Robot Learning: A Tutorial (arXiv:2510.12403)", desc: "HF × 牛津，2025-10。经典机器人学 → RL/BC → 生成模型 → 通用语言条件策略，附 LeRobot 示例。最推荐的第一篇通读材料。", url: "https://arxiv.org/abs/2510.12403", verified: true },
    { kind: "paper", name: "VLA Models for Robotics: A Review (IEEE Access 2025)", desc: "含可筛选 / 排序的 VLA 模型交互表（Category / Task / Modality / Robot / Backbone）。", url: "https://vla-survey.github.io/", verified: true },
    { kind: "paper", name: "World Models for Embodied AI 综述 (arXiv:2510.16732)", desc: "2025-10，功能–时间–空间三轴分类框架。世界模型术语未统一，读一篇建立坐标系即可。", url: "https://arxiv.org/abs/2510.16732" },
    { kind: "paper", name: "Physical Simulators and World Models 综述 (arXiv:2507.00917)", desc: "南京大学等，v3 2025-09；附持续更新的文献仓库，仿真器 × 世界模型双主线。", url: "https://arxiv.org/abs/2507.00917" },
    { kind: "paper", name: "OpenVLA 论文与项目页", desc: "7B 参数，Open X-Embodiment 97 万 episodes，代码与权重开源、支持单卡 LoRA 微调。", url: "https://openvla.github.io/", verified: true },
    { kind: "paper", name: "Diffusion Policy (arXiv:2303.04137)", desc: "扩散策略开山作；50–150 条演示即可训练，理解生成式策略的必读。", url: "https://arxiv.org/abs/2303.04137" },
    { kind: "paper", name: "Sim-to-Real Transfer in Deep RL: A Survey", desc: "Sim2Real 经典综述（arXiv:2009.13303），讲清 gap 来源与域随机化脉络。", url: "https://arxiv.org/abs/2009.13303" },
    { kind: "docs", name: "ROS 2 官方文档", desc: "新手教程、包索引、Discourse。发行版与支持期以官网为准（Lyrical / Jazzy / Humble）。", url: "https://docs.ros.org/", verified: true },
    { kind: "docs", name: "LeRobot 仓库与文档", desc: "端到端机器人学习：数据集格式 + 策略 + 真机控制 + 评估，含 SO-101 指南。", url: "https://github.com/huggingface/lerobot", verified: true },
    { kind: "docs", name: "Gymnasium", desc: "Farama Foundation 维护的 RL 环境 API 标准，reset / step 五元组，含 Gym 迁移指南。", url: "https://gymnasium.farama.org/", verified: true },
    { kind: "docs", name: "Stable-Baselines3 / RoboMimic", desc: "前者一行调用 PPO / SAC，后者做离线 IL 与标准化评测对照实验。", url: "https://stable-baselines3.readthedocs.io/", verified: true },
    { kind: "docs", name: "Isaac Lab 文档与仓库", desc: "GPU 并行 RL / IL 框架，BSD-3；安装前务必查官方 Isaac Sim 版本兼容表。", url: "https://isaac-sim.github.io/IsaacLab/main/", verified: true },
    { kind: "docs", name: "Open X-Embodiment", desc: "跨本体预训练事实标准数据集；软件 Apache 2.0，商用需逐个数据集查许可。", url: "https://github.com/google-deepmind/open_x_embodiment" },
    { kind: "docs", name: "Gazebo / MuJoCo / LIBERO", desc: "ROS2 原生全系统仿真、接触丰富的操作物理引擎、VLA 微调标准基准。", url: "https://gazebosim.org/docs/latest/getstarted/" },
    { kind: "cn", name: "DataWhale · 从零开始学具身智能", desc: "中文免费路径覆盖 Python → 机器人学 → 仿真 → CV → 规划 → RL → VLA。", url: "https://www.datawhale.cn/", verified: true },
    { kind: "cn", name: "CSDN DAMO 开发者矩阵", desc: "VLA 前沿研究报告、零基础学习路线、机器人行业招聘信息，更新快但数字需回原始来源核对。", url: "https://damodev.csdn.net/" },
    { kind: "cn", name: "机器之心 / EmboX 具身工坊", desc: "中文资讯与 LeRobot Push-T 等实战解读；公众号内容按标题检索。", url: "" },
    { kind: "cn", name: "ROSChina / 智源社区 / 古月居", desc: "中文排坑与交流社区。本轮未验证到稳定 URL，仅列名称，避免编造链接。", url: "" },
    { kind: "contest", name: "RoboCup 2026（韩国仁川）", desc: "RoboCup 2026 首次由韩国主办；联赛含 Soccer、Rescue、@Home、Industrial、Junior。", url: "https://www.robocup.org/", verified: true },
    { kind: "contest", name: "中国机器人大赛暨 RoboCup 中国赛", desc: "2025 石家庄站 300 余所高校、近 1700 支队伍；首次增设「智源具身大模型挑战赛」，国家级赛事首个具身专项赛道。", url: "https://www.stdaily.com/web/gdxw/2025-10/20/content_418037.html" },
    { kind: "contest", name: "人形机器人专项赛 / LeRobot 黑客松", desc: "2025 合肥站近 400 所高校参与；HF LeRobot 全球黑客松 2025 年约 3000 人参与，适合零真机练手。", url: "" },
  ];

  const TEMPLATES = [
    {
      key: "repro",
      name: "复现记录",
      desc: "跑通一个开源项目后，把过程、超参与失败案例写清楚。",
      title: "【复现】",
      tags: "具身智能,复现记录",
      preview: "项目 / 版本 / 随机种子：\n数据：\n超参：\n成功率（基线 → 我的）：\n失败案例与原因：\n下一步：",
      content: "## 我在复现什么\n\n- 项目与版本：\n- 环境（GPU / CUDA / 关键依赖）：\n- 随机种子与配置文件：\n\n## 数据\n\n- 数据集与规模（注明口径）：\n\n## 超参\n\n- \n\n## 结果\n\n- 基线成功率 → 我的成功率：\n- 奖励曲线 / 评估截图：（可插图）\n\n## 失败案例与原因\n\n- \n\n## 想请教大家\n\n- ",
    },
    {
      key: "env",
      name: "环境踩坑",
      desc: "版本冲突、CUDA、Isaac / ROS2 配对，最常被搜索的一类帖子。",
      title: "【踩坑】",
      tags: "具身智能,环境配置",
      preview: "系统 / GPU：\n报错原文：\n已试过：\n最终解法：\n版本锁定清单：",
      content: "## 环境\n\n- OS / GPU / 驱动：\n- Python / CUDA / PyTorch：\n- 相关框架版本：\n\n## 报错原文\n\n```text\n\n```\n\n## 已试过但没用\n\n- \n\n## 最终解法\n\n- \n\n## 版本锁定清单\n\n- ",
    },
    {
      key: "hardware",
      name: "硬件选型",
      desc: "SO-101、摄像头、电源、夹具的真实成本与坑，比参数表有用。",
      title: "【选型】",
      tags: "具身智能,硬件",
      preview: "预算：\n已有设备：\n候选方案：\n隐藏成本：\n想问：",
      content: "## 我的条件\n\n- 预算：\n- 已有设备（GPU / 机械臂 / 相机）：\n\n## 候选方案\n\n- \n\n## 隐藏成本\n\n摄像头、电源、夹具、3D 打印耗材、调试时间……\n\n## 想问大家\n\n- ",
    },
    {
      key: "paper",
      name: "论文共读",
      desc: "每周一篇，把架构图翻译成「数据怎么进、动作怎么出」。",
      title: "【共读】",
      tags: "具身智能,论文共读",
      preview: "论文 / 链接：\n一句话结论：\n数据格式与动作表示：\n我没看懂的地方：",
      content: "## 论文\n\n- 标题 / arXiv 链接：\n- 一句话结论：\n\n## 架构\n\n- 图像 token / 语言 token / 动作 token 分别怎么进网络：\n- 动作表示（离散 or 连续、chunk 长度、推理频率）：\n\n## 数据\n\n- 训练集与规模口径：\n\n## 我没看懂的地方\n\n- ",
    },
  ];

  // 社区化模板：所有入口都带着「我正在看什么」的上下文跳到论坛编辑器。
  TEMPLATES.push(
    {
      key: "free", name: "自由发帖", desc: "只带 #具身智能 标签，正文自由发挥。", title: "【具身智能】", tags: "具身智能", preview: "我想聊什么 / 背景 / 想请教大家",
      content: "## 我想聊什么\n\n- \n\n## 背景 / 我试过什么\n\n- \n\n## 想请教大家\n\n- ",
    },
    {
      key: "showcase", name: "晒产出", desc: "把复现、曲线、视频或报告发出来换反馈。", title: "【作品集】", tags: "具身智能,作品集", preview: "做了什么 / 怎么验的 / 失败案例 / 想让大家看什么",
      content: "## 做了什么\n\n- 项目 / 任务：\n- 代码或视频链接：\n\n## 怎么验的\n\n- 基线 → 我的结果：\n- 环境、版本、随机种子：\n\n## 失败案例\n\n- \n\n## 希望大家帮我看\n\n- ",
    },
    {
      key: "question", name: "带上下文提问", desc: "自动带上你正在看的任务或项目，别人才答得上。", title: "【求解答】", tags: "具身智能,答疑", preview: "现象与报错 / 环境 / 已试过 / 我的猜测",
      content: "## 现象与报错\n\n```text\n\n```\n\n## 环境\n\n- OS / GPU / CUDA / PyTorch：\n- 相关框架版本：\n\n## 已经试过\n\n- \n\n## 我的猜测\n\n- ",
    },
    {
      key: "news", name: "行业动态讨论", desc: "把一条动态连原文一起带进帖子，聊它对求职的影响。", title: "【动态】", tags: "具身智能,行业动态", preview: "在说什么 / 对入行者的意义 / 我的疑问",
      content: "## 这条动态在说什么\n\n- \n\n## 对入行 / 找工作的人意味着什么\n\n- \n\n## 我的疑问\n\n- ",
    },
    {
      key: "price", name: "硬件报价纠错", desc: "带型号、实付价、渠道和日期，帮所有人校准价格表。", title: "【报价】", tags: "具身智能,硬件", preview: "型号 / 实付价 / 成交日期 / 隐藏成本 / 踩坑提醒",
      content: "## 设备\n\n- 型号 / 配置：\n- 购买渠道：\n- 实付价格与币种：\n- 成交日期：\n\n## 是否含税 / 运费 / 配件\n\n- \n\n## 踩坑提醒\n\n- 是否可二次开发、是否需要额外买 EDU 版：",
    }
  );

  const GLOSSARY = [
    { term: "VLA", plain: "把摄像头画面 + 一句人话指令，直接翻译成机器人动作的神经网络。", why: "现在招聘里最高频的词，理解它就知道整条链路在干什么。" },
    { term: "action chunk", plain: "模型一次预测未来一小串动作，而不是每一帧都重新想一遍。", why: "ACT / Diffusion Policy / π0 都绕不开它，也直接影响控制频率。" },
    { term: "Sim2Real", plain: "在仿真里练好的策略，搬到真机上还能用。", why: "仿真成功率不等于真机成功率，这是最常见的翻车点。" },
    { term: "行为克隆 BC", plain: "给人类的示范动作做监督学习：看到这个状态，就模仿这个动作。", why: "最简单的模仿学习基线，所有复现都拿它当对照。" },
    { term: "遥操作", plain: "人用主手 / 手柄操控机器人做一遍任务，顺手把数据录下来。", why: "真机数据就是这么来的，数据采集岗的日常。" },
    { term: "episode / 轨迹", plain: "一次完整任务录制，从开始到成功或失败的一串观测与动作。", why: "数据集规模、演示条数都按它数，口径一定要写清。" },
    { term: "URDF", plain: "描述机器人「有几根杆、怎么连、能往哪转」的 XML 文件。", why: "仿真和 ROS2 都靠它认识你的机器人。" },
    { term: "末端执行器", plain: "机械臂最前端那部分：夹爪、吸盘、灵巧手。", why: "同一套算法换个夹爪就可能完全不work，作品集里要写清。" },
    { term: "域随机化", plain: "训练时故意把光照、摩擦、质量等参数乱调，逼模型别只记住一个环境。", why: "缩小 sim2real gap 最实用的手段之一。" },
    { term: "ROS2 topic", plain: "机器人各模块之间收发消息的「广播频道」，比如相机持续往外发图像。", why: "不懂 topic 就看不懂机器人系统为什么延迟高。" },
    { term: "奖励曲线", plain: "强化学习训练过程中，每轮拿到的分数随步数变化的折线。", why: "面试最常让你解释的一张图：震荡、崩塌、假收敛。" },
    { term: "LoRA", plain: "只训练大模型旁边的一小层参数，不改动原模型。", why: "单卡微调 VLA 的现实路径，全量 7B 训练对自学不现实。" },
  ];

  const state = {
    user: null, track: null, done: new Set(), synced: false, topics: [],
    newsKind: "all", newsItems: [], newsFromApi: false,
    hwTier: "all", hwNeedle: "", lastRoute: "start",
  };

  function readLocal(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (_) { return fallback; }
  }
  function writeLocal(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* 隐私模式 */ }
  }
  async function api(url, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const response = await fetch(url, Object.assign({ credentials: "same-origin" }, options, { headers }));
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || ("请求未完成（" + response.status + "）"));
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function toast(message) {
    const box = document.getElementById("forum-toast");
    if (!box) return;
    box.textContent = message;
    box.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => box.classList.remove("show"), 3200);
  }
  function resolveUser() {
    const pending = window.kflowAuthReady;
    if (pending && typeof pending.then === "function") return pending.catch(() => null);
    return Promise.resolve(null);
  }
  function requireLogin(action) {
    if (state.user) return true;
    toast("请先登录，才能" + action);
    const link = document.getElementById("siteLoginLink");
    if (link) link.focus();
    return false;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function externalLink(url, label) {
    const a = el("a", "", label || url);
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }

  /* ── 发帖模板种子（论坛编辑器消费） ───────────────────────────────────
     context 允许各卡片把自己当成「上下文」带进正文，用户不必重新描述
     正在看哪个任务 / 哪条动态 / 哪个设备。
     ───────────────────────────────────────────────────────────────────── */
  function lrcCompose(key, context) {
    const tpl = TEMPLATES.find((item) => item.key === key) || TEMPLATES.find((item) => item.key === "free");
    const ctx = context && typeof context === "object" ? context : {};
    const lines = (ctx.lines || []).filter((line) => typeof line === "string" && line);
    const extraTags = (ctx.tags || []).filter((tag) => typeof tag === "string" && tag);
    const tags = Array.from(new Set((tpl.tags || "具身智能").split(",").concat(extraTags)))
      .filter(Boolean).slice(0, 5).join(",");
    const header = lines.length
      ? "> 来自 LRobotcup 专题 · 我正在看的内容\n>\n" + lines.map((line) => "> " + line).join("\n") + "\n\n"
      : "";
    const seed = {
      title: (tpl.title || "【具身智能】") + (ctx.titleSuffix || ""),
      tags: tags,
      content: header + (tpl.content || ""),
    };
    try {
      sessionStorage.setItem(COMPOSE_SEED_KEY, JSON.stringify(seed));
    } catch (_) {
      /* 隐私模式下 sessionStorage 不可写：仍然正常跳转发帖页 */
    }
  }
  window.lrcCompose = lrcCompose;

  function composeLink(label, templateKey, context, className) {
    const a = el("a", className || "lrc-mini-btn", label);
    a.href = COMPOSE_URL;
    a.addEventListener("click", () => lrcCompose(templateKey, context));
    return a;
  }

  /* ── 岗位方向 ───────────────────────────────────────────────────────── */
  function renderRoles() {
    const host = document.getElementById("lrcRoles");
    if (!host) return;
    ROLES.forEach((role, index) => {
      const box = el("details", "lrc-role");
      const summary = el("summary");
      summary.append(el("span", "lrc-role-id", String(index + 1)), el("span", "", role.name));
      const body = el("div", "lrc-role-body");
      body.append(el("p", "", "职责：" + role.duty));
      const skills = el("p", "");
      skills.append(el("strong", "", "硬性能力："), document.createTextNode(role.skills));
      body.append(skills);
      const keywords = el("div", "lrc-keywords");
      role.keywords.forEach((word) => keywords.append(el("span", "lrc-keyword", word)));
      body.append(keywords);
      box.append(summary, body);
      host.append(box);
    });
  }

  /* ── 阶段 tab ───────────────────────────────────────────────────────── */
  function initStages() {
    const tabs = Array.from(document.querySelectorAll(".lrc-tab[data-stage]"));
    const panels = Array.from(document.querySelectorAll("[data-stage-panel]"));
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const stage = tab.dataset.stage;
        tabs.forEach((item) => {
          const active = item === tab;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-selected", active ? "true" : "false");
        });
        panels.forEach((panel) => {
          const active = panel.dataset.stagePanel === stage;
          panel.classList.toggle("is-active", active);
          panel.hidden = !active;
        });
        renderWeek();
        markRelatedTasks();
      });
    });
  }

  /* ── 学习进度：登录落 LearnProgress，游客降级 localStorage ─────────── */
  function paintProgress() {
    const boxes = Array.from(document.querySelectorAll("[data-lrc-task]"));
    if (!boxes.length) return;
    const finished = boxes.filter((box) => state.done.has(box.dataset.lrcTask)).length;
    const percent = Math.round((finished / boxes.length) * 100);
    const badge = document.getElementById("lrcProgress");
    if (badge) badge.textContent = "路线完成度 " + percent + "%";
    const sync = document.getElementById("lrcSyncState");
    if (sync) sync.textContent = state.user
      ? (state.synced ? "已同步到社区账号" : "同步中，先存本机")
      : "游客模式：进度仅存本机";
    const box = document.getElementById("lrcProgressState");
    if (box) {
      box.replaceChildren();
      box.append(el("strong", "", percent + "%"), document.createTextNode(" · " + finished + " / " + boxes.length + " 个任务"));
      box.append(el("br", ""), document.createTextNode(
        state.user
          ? (state.synced ? "勾选会同步到账号，换设备也在，并计入学习成就与等级。" : "正在与社区账号同步…")
          : "登录后同步到账号并计入学习成就；现在先存在这台浏览器。"
      ));
    }
  }

  function renderWeek() {
    const host = document.getElementById("lrcWeekList");
    if (!host) return;
    const panel = document.querySelector(".lrc-stage.is-active") || document.querySelector("[data-stage-panel]");
    const boxes = panel ? Array.from(panel.querySelectorAll("[data-lrc-task]")) : [];
    const pending = boxes.filter((box) => !state.done.has(box.dataset.lrcTask)).slice(0, 3);
    host.replaceChildren();
    if (!pending.length) {
      host.append(el("li", "", "这一阶段的任务都勾完了，切到下一阶段继续 →"));
      return;
    }
    pending.forEach((box, index) => {
      const label = box.closest("label");
      const li = el("li");
      li.append(el("span", "lrc-week-no", String(index + 1)));
      li.append(el("span", "", label ? label.textContent.trim() : box.dataset.lrcTask));
      host.append(li);
    });
  }

  function checkinLink(taskText) {
    const btn = el("button", "lrc-mini-btn", "晒进展");
    btn.type = "button";
    btn.addEventListener("click", () => openCheckin(taskText));
    return btn;
  }

  function attachTaskActions() {
    document.querySelectorAll(".lrc-tasks li").forEach((li) => {
      const box = li.querySelector("[data-lrc-task]");
      if (!box || li.querySelector(".lrc-task-actions")) return;
      const label = li.querySelector("label");
      const text = label ? label.textContent.trim() : box.dataset.lrcTask;
      const actions = el("span", "lrc-task-actions");
      actions.append(
        composeLink("问一问", "question", {
          lines: ["学习任务：" + text, "任务编号：" + box.dataset.lrcTask],
          titleSuffix: text.slice(0, 18), tags: ["答疑"],
        }),
        checkinLink(text)
      );
      li.append(actions);
    });
  }

  async function onTaskToggle(box) {
    const key = box.dataset.lrcTask;
    if (box.checked) state.done.add(key);
    else state.done.delete(key);
    writeLocal(PROGRESS_KEY, Array.from(state.done));
    paintProgress();
    renderWeek();
    if (!state.user) return;
    try {
      const data = await api(box.checked ? "/api/learn/complete" : "/api/learn/uncomplete", {
        method: "POST", body: JSON.stringify({ kind: "tutorial", slug: "lrc-" + key }),
      });
      state.synced = true;
      if (box.checked && data.newBadges && data.newBadges.length && window.kflowCelebrate) {
        window.kflowCelebrate.badges(data.newBadges);
      }
    } catch (_) {
      state.synced = false;
      toast("进度已存本机，与社区同步失败，稍后再试");
    }
    paintProgress();
  }

  async function initProgress() {
    const boxes = Array.from(document.querySelectorAll("[data-lrc-task]"));
    if (!boxes.length) return;
    const local = readLocal(PROGRESS_KEY, []);
    (Array.isArray(local) ? local : []).forEach((key) => {
      if (typeof key === "string") state.done.add(key);
    });
    attachTaskActions();
    paintProgress();
    renderWeek();

    const user = await resolveUser();
    state.user = user && user.username ? user : null;
    if (state.user) {
      try {
        const data = await api("/api/learn/progress?kind=tutorial");
        const remote = (data.items || [])
          .filter((slug) => typeof slug === "string" && slug.indexOf("lrc-") === 0)
          .map((slug) => slug.slice(4));
        const remoteSet = new Set(remote);
        remote.forEach((key) => state.done.add(key));
        const toSync = Array.from(state.done).filter((key) => !remoteSet.has(key));
        await Promise.all(toSync.map((key) => api("/api/learn/complete", {
          method: "POST", body: JSON.stringify({ kind: "tutorial", slug: "lrc-" + key }),
        }).catch(() => null)));
        state.synced = true;
        writeLocal(PROGRESS_KEY, Array.from(state.done));
      } catch (_) {
        state.synced = false;
      }
    }
    boxes.forEach((box) => {
      box.checked = state.done.has(box.dataset.lrcTask);
      box.addEventListener("change", () => onTaskToggle(box));
    });
    paintProgress();
    renderWeek();
  }

  /* ── 项目推荐 ───────────────────────────────────────────────────────── */
  function projectCard(project) {
    const card = el("div", "lrc-card lrc-project");
    const top = el("div", "lrc-project-top");
    const level = el("span", "lrc-level", LEVEL_LABEL[project.level] || project.level);
    level.dataset.level = project.level;
    top.append(level, el("span", "lrc-tag", "项目"));
    card.append(top, el("h3", "", project.name), el("p", "", project.desc));
    const meta = el("div", "lrc-meta");
    const hardware = el("div", "");
    hardware.append(el("strong", "", "硬件："), document.createTextNode(project.hardware));
    const output = el("div", "");
    output.append(el("strong", "", "产出："), document.createTextNode(project.output));
    meta.append(hardware, output);
    card.append(meta, externalLink(project.link, "打开项目 / 文档 ↗"));
    const actions = el("div", "lrc-track-actions");
    actions.append(
      composeLink("问一问", "question", {
        lines: ["项目：" + project.name, "硬件门槛：" + project.hardware, "可展示产出：" + project.output],
        titleSuffix: project.name.slice(0, 18), tags: ["项目"],
      }),
      checkinLink(project.name)
    );
    card.append(actions);
    return card;
  }

  function initProjects() {
    const host = document.getElementById("lrcProjects");
    const filters = document.getElementById("lrcProjectFilters");
    if (!host || !filters) return;
    const paint = (level) => {
      host.replaceChildren();
      PROJECTS.filter((item) => level === "all" || item.level === level)
        .forEach((item) => host.append(projectCard(item)));
    };
    filters.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-project-filter]");
      if (!chip) return;
      filters.querySelectorAll(".lrc-chip").forEach((item) => item.classList.toggle("is-active", item === chip));
      paint(chip.dataset.projectFilter);
    });
    paint("all");
  }

  /* ── 资源库 ─────────────────────────────────────────────────────────── */
  const KIND_LABEL = {
    course: "课程", book: "教材", paper: "论文 / 综述",
    docs: "官方文档", cn: "中文社区", contest: "竞赛",
  };

  function resourceCard(resource) {
    const card = el("div", "lrc-card lrc-resource");
    const top = el("div", "lrc-resource-top");
    top.append(el("span", "lrc-resource-kind", KIND_LABEL[resource.kind] || resource.kind));
    if (resource.verified) top.append(el("span", "lrc-verified", "已验证"));
    card.append(top, el("h3", "", resource.name), el("p", "", resource.desc));
    if (resource.url) card.append(externalLink(resource.url, resource.url.replace(/^https?:\/\//, "").replace(/\/$/, "") + " ↗"));
    else card.append(el("span", "lrc-topic-sub", "本轮未验证到稳定 URL，按名称检索"));
    return card;
  }

  function initResources() {
    const host = document.getElementById("lrcResources");
    const filters = document.getElementById("lrcResourceFilters");
    const search = document.getElementById("lrcResourceSearch");
    const empty = document.getElementById("lrcResourceEmpty");
    if (!host || !filters) return;
    let kind = "all";
    let needle = "";
    const paint = () => {
      const list = RESOURCES.filter((item) => {
        if (kind !== "all" && item.kind !== kind) return false;
        if (!needle) return true;
        const haystack = (item.name + " " + item.desc + " " + (item.url || "")).toLowerCase();
        return haystack.includes(needle);
      });
      host.replaceChildren();
      list.forEach((item) => host.append(resourceCard(item)));
      if (empty) empty.hidden = list.length > 0;
    };
    filters.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-resource-filter]");
      if (!chip) return;
      kind = chip.dataset.resourceFilter;
      filters.querySelectorAll(".lrc-chip").forEach((item) => item.classList.toggle("is-active", item === chip));
      paint();
    });
    if (search) {
      search.addEventListener("input", () => {
        needle = search.value.trim().toLowerCase();
        paint();
      });
    }
    paint();
  }

  /* ── 开帖模板 ───────────────────────────────────────────────────────── */
  function initTemplates() {
    const host = document.getElementById("lrcTemplates");
    if (!host) return;
    TEMPLATES.forEach((tpl) => {
      const card = el("div", "lrc-card lrc-template");
      card.append(el("h4", "", tpl.name), el("p", "", tpl.desc), el("pre", "", tpl.preview));
      const btn = el("a", "lrc-btn lrc-btn-primary", "用这个模板发帖");
      btn.href = COMPOSE_URL;
      btn.addEventListener("click", () => lrcCompose(tpl.key));
      card.append(btn);
      host.append(card);
    });
  }

  /* ── 交流贴：按 #具身智能 标签精确拉取，带点赞与同路人聚合 ─────────── */
  function initTopics() {
    const host = document.getElementById("lrcTopics");
    const filters = document.getElementById("lrcTopicFilters");
    if (!host || !filters) return;
    let requestSeq = 0;

    function emptyState(message) {
      host.replaceChildren();
      const box = el("p", "lrc-topic-empty");
      box.append(el("strong", "", message), document.createTextNode(" 还没有相关讨论。"));
      const link = el("a", "lrc-discuss-foot-link", "来开第一帖 →");
      link.href = COMPOSE_URL;
      link.style.cssText = "display:inline-block;margin:10px 0 0;color:var(--lrc-accent-2);font-weight:700;text-decoration:none";
      link.addEventListener("click", () => lrcCompose("free"));
      box.append(el("br", ""), link);
      host.append(box);
    }

    function renderPeople(items) {
      const people = document.getElementById("lrcPeople");
      if (!people) return;
      const counts = new Map();
      items.forEach((item) => {
        const name = item.author || "匿名";
        counts.set(name, (counts.get(name) || 0) + 1);
      });
      people.replaceChildren();
      if (!counts.size) {
        people.append(el("p", "lrc-inline-notice", "还没有人发过带 #具身智能 标签的帖子。你可以是第一个。"));
        return;
      }
      Array.from(counts.entries()).slice(0, 8).forEach(([name, count]) => {
        const a = el("a", "lrc-person");
        a.href = "/forum?q=" + encodeURIComponent(name);
        a.append(
          el("span", "lrc-avatar", String(name).slice(0, 1).toUpperCase()),
          el("span", "", name),
          el("small", "", " · " + count + " 帖")
        );
        people.append(a);
      });
    }

    function topicItem(item) {
      const row = el("div", "lrc-topic-item");
      const main = el("div", "lrc-topic-main");
      const title = el("a", "lrc-topic-title", item.title || "未命名话题");
      title.href = "/forum?topic=" + encodeURIComponent(item.id);
      const bits = [item.category || "社区", item.author || "匿名", (item.replies || 0) + " 条回复", (item.views || 0) + " 浏览"];
      main.append(title, el("span", "lrc-topic-sub", bits.join(" · ")));
      row.append(main);
      const like = el("button", "lrc-mini-btn", (item.liked ? "♥ " : "♡ ") + (item.likes || 0));
      like.type = "button";
      like.setAttribute("aria-label", "点赞这个话题");
      like.addEventListener("click", async () => {
        if (!requireLogin("点赞")) return;
        try {
          const data = await api("/api/forum/topics/" + item.id + "/like", {
            method: item.liked ? "DELETE" : "POST",
          });
          item.liked = Boolean(data.liked);
          item.likes = data.likes || 0;
          like.textContent = (item.liked ? "♥ " : "♡ ") + item.likes;
        } catch (error) {
          toast(error.message);
        }
      });
      row.append(like);
      return row;
    }

    async function load(params) {
      const seq = ++requestSeq;
      host.replaceChildren(el("p", "lrc-topic-loading", "正在加载社区讨论…"));
      const query = new URLSearchParams({ page_size: "8" });
      Object.keys(params || {}).forEach((key) => {
        if (params[key]) query.set(key, params[key]);
      });
      try {
        const res = await fetch("/api/forum/topics?" + query.toString());
        const data = await res.json().catch(() => ({}));
        if (seq !== requestSeq) return;
        const items = Array.isArray(data.items) ? data.items : [];
        state.topics = items;
        renderPeople(items);
        if (!res.ok || !items.length) {
          emptyState(res.ok ? "这个筛选下" : "论坛暂时不可用，");
          return;
        }
        host.replaceChildren();
        items.forEach((item) => host.append(topicItem(item)));
      } catch (_) {
        if (seq === requestSeq) emptyState("网络未连通，");
      }
    }

    filters.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-topic-tag], [data-topic-q]");
      if (!chip) return;
      filters.querySelectorAll(".lrc-chip").forEach((item) => item.classList.toggle("is-active", item === chip));
      if (chip.dataset.topicTag) load({ tag: chip.dataset.topicTag });
      else load({ q: chip.dataset.topicQ });
    });
    window.lrcLoadTopics = load;
    load({ tag: "具身智能" });
  }

  /* ── 30 秒自测：给零基础用户一个明确起点 ───────────────────────────── */
  const GOAL_TRACK = { algo: "vla", sys: "deployment", hw: "control", unsure: "" };
  const PY_STEPS = {
    no: [
      "今天：装好 Python，跑通 Hugging Face Robotics Course 第 0 单元；看不懂没关系，先把环境跑起来。",
      "本周：在 Colab 打开 LeRobot 的示例 notebook，把报错和解法记进一个 Git 仓库。",
      "别做：买机械臂、开始啃 VLA 论文、同时开三门课。",
    ],
    some: [
      "今天：在 Colab / 本机跑通 LeRobot Push-T 的一次训练，截图训练曲线。",
      "本周：勾完阶段一清单，并写一页「观测 / 动作 / action chunk 是什么」的笔记。",
      "别做：一上来微调 7B 模型，先用 450M 级 SmolVLA 或纯仿真基线。",
    ],
    yes: [
      "今天：挑一个经典复现（ACT 或 Diffusion Policy），按官方 README 跑通基线。",
      "本周：做一次对照实验（演示条数 / 超参），把成功率与失败案例写成复现帖。",
      "别做：只刷 SOTA 论文；企业更看重你能不能把闭环跑通并讲清失败。",
    ],
  };
  const HW_NOTE = {
    none: "硬件路径：零成本起步完全可行，纯仿真 + 公开数据集就能完成阶段一，先别花钱。",
    gpu: "硬件路径：你有独显或云 GPU，可以跳过 Colab 额度限制，直接做本地复现与小规模微调。",
    arm: "硬件路径：已有真机，重点补采集 SOP、标定与 sim/real 对照实验，这是最稀缺的作品集素材。",
  };

  function initQuiz() {
    const py = document.getElementById("lrcQuizPy");
    const hw = document.getElementById("lrcQuizHw");
    const goal = document.getElementById("lrcQuizGoal");
    const out = document.getElementById("lrcQuizResult");
    if (!py || !hw || !goal || !out) return;
    const STAGE_LABEL = { no: "阶段一 · 先跑通最小闭环", some: "阶段一为主，顺手看阶段二", yes: "阶段一快速过，主攻阶段二" };

    function render() {
      const steps = (PY_STEPS[py.value] || PY_STEPS.no).slice();
      steps.push(HW_NOTE[hw.value] || HW_NOTE.none);
      const track = TRACKS.find((item) => item.id === GOAL_TRACK[goal.value]);
      out.replaceChildren();
      out.append(
        el("h4", "", "建议起点：" + (STAGE_LABEL[py.value] || STAGE_LABEL.no)),
        el("p", "", track
          ? "按你的选择，可以先看「" + track.name + "」，但别现在就把自己锁死——跑完阶段一再确认也来得及。"
          : "方向还没想清楚很正常。先按阶段一跑一遍最小闭环，用「做过什么」而不是「想做什么」来选方向。")
      );
      const list = el("ul", "lrc-quiz-steps");
      steps.forEach((step) => list.append(el("li", "", step)));
      out.append(list);
      const links = el("div", "lrc-quiz-links");
      const a1 = el("a", "lrc-mini-btn", "去看这一阶段的任务");
      a1.href = "#roadmap";
      const a2 = el("a", "lrc-mini-btn", "先扫一眼 12 个术语");
      a2.href = "#start";
      const a3 = el("a", "lrc-mini-btn", track ? "把「" + track.name + "」设为主攻" : "先逛 8 个方向");
      a3.href = "#tracks";
      a3.addEventListener("click", () => { if (track) applyTrack(track.id); });
      links.append(a1, a2, a3);
      out.append(links);
    }
    [py, hw, goal].forEach((select) => select.addEventListener("change", render));
    render();
  }

  function initGlossary() {
    const host = document.getElementById("lrcGlossary");
    if (!host) return;
    host.replaceChildren();
    GLOSSARY.forEach((entry) => {
      const box = el("details");
      box.append(el("summary", "", entry.term), el("p", "", entry.plain + " 为什么现在就要管：" + entry.why));
      host.append(box);
    });
  }

  const PORTFOLIO = [
    "一个带 README、锁定版本与随机种子的复现仓库",
    "一张训练曲线 + 基线对比 + 失败案例分析",
    "一段仿真或真机执行视频，敢把失败片段也放进去",
    "一份数据字典与采集 SOP，写清规模口径与摄像头视角",
    "一篇复现笔记或论文共读帖，能讲清「数据怎么进、动作怎么出」",
    "一个给开源项目提的 PR 或 issue，文档纠错也算",
  ];

  function initPortfolio() {
    const host = document.getElementById("lrcPortfolio");
    if (!host) return;
    host.replaceChildren();
    PORTFOLIO.forEach((text) => host.append(el("li", "", text)));
  }

  /* ── 就业子方向：选一个，页面跟着重排 ───────────────────────────────── */
  function trackCard(track) {
    const selected = state.track && state.track.id === track.id;
    const card = el("article", "lrc-track" + (selected ? " is-selected" : ""));
    const top = el("div", "lrc-track-top");
    const heading = el("h3", "", track.name || "");
    heading.append(el("span", "lrc-track-en", track.enName || ""));
    const badge = el("span", "lrc-track-badge", track.demand === "hot" ? "需求热" : "稳定需求");
    badge.dataset.demand = track.demand || "steady";
    top.append(heading, badge);
    card.append(top, el("p", "", track.oneLiner || ""));

    const skills = el("div");
    skills.append(el("div", "lrc-track-label", "核心技能"));
    const chips = el("div", "lrc-track-chips");
    (track.hardSkills || []).slice(0, 6).forEach((skill) => chips.append(el("span", "", skill)));
    skills.append(chips);
    card.append(skills);

    const detail = el("details", "lrc-track-detail");
    detail.append(el("summary", "", "展开：JD 关键词 / 练手项目 / 作品集 / 面试 / 坑"));
    const dl = el("dl");
    const rows = [
      ["为什么招这个岗", track.whyHire],
      ["适合什么背景", track.background],
      ["JD 高频词", (track.jdKeywords || []).join("、")],
      ["工具", (track.tools || []).join("、")],
      ["练手项目", (track.entryProjects || []).join("；")],
      ["可展示产出", track.portfolio],
      ["面试考点", (track.interviewTopics || []).join("；")],
      ["新手常踩的坑", track.pitfall],
    ];
    rows.forEach(([key, value]) => {
      if (!value) return;
      dl.append(el("dt", "", key), el("dd", "", value));
    });
    detail.append(dl);
    card.append(detail);

    const actions = el("div", "lrc-track-actions");
    const choose = el("button", "lrc-mini-btn", selected ? "已设为主攻" : "设为主攻方向");
    choose.type = "button";
    choose.addEventListener("click", () => applyTrack(selected ? "" : track.id));
    actions.append(choose, composeLink("找这个方向的讨论", "question", {
      lines: ["目标方向：" + track.name, "JD 关键词：" + (track.jdKeywords || []).slice(0, 5).join("、")],
      titleSuffix: String(track.name).slice(0, 16), tags: ["方向选择"],
    }));
    card.append(actions);
    return card;
  }

  function renderTracks() {
    const host = document.getElementById("lrcTracks");
    if (!host) return;
    host.replaceChildren();
    if (!TRACKS.length) {
      host.append(el("p", "lrc-inline-notice", "方向数据尚未加载。"));
      return;
    }
    TRACKS.forEach((track) => host.append(trackCard(track)));
  }

  function renderTrackBanner() {
    const host = document.getElementById("lrcTrackBanner");
    if (!host) return;
    host.replaceChildren();
    if (!state.track) {
      host.append(el("span", "", "还没选方向也没关系：先按阶段一跑一遍最小闭环，再回来挑。"));
      host.append(composeLink("让社区帮我选方向", "question", {
        lines: ["我的情况：（Python / 硬件 / 每周可投入时间）", "纠结点：（算法还是工程？要不要上真机？）"],
        titleSuffix: "该选哪个方向", tags: ["方向选择"],
      }));
      return;
    }
    const track = state.track;
    host.append(el("span", "", "当前主攻："), el("strong", "", track.name),
      el("span", "", " · 已高亮相关任务，交流贴按该方向关键词筛选"));
    const see = el("a", "lrc-mini-btn", "看该方向的社区帖子");
    see.href = "#discuss";
    see.addEventListener("click", () => {
      if (window.lrcLoadTopics) window.lrcLoadTopics({ q: (track.jdKeywords || [])[0] || track.name });
    });
    const clear = el("button", "lrc-mini-btn", "清除选择");
    clear.type = "button";
    clear.addEventListener("click", () => applyTrack(""));
    host.append(see, clear);
  }

  function markRelatedTasks() {
    const ids = new Set(((state.track && state.track.relatedTaskSlugs) || [])
      .map((slug) => String(slug).replace(/^lrc-/, "")));
    document.querySelectorAll(".lrc-tasks li").forEach((li) => {
      const box = li.querySelector("[data-lrc-task]");
      li.classList.toggle("is-related", Boolean(box && ids.has(box.dataset.lrcTask)));
    });
  }

  function applyTrack(id) {
    state.track = TRACKS.find((track) => track.id === id) || null;
    writeLocal(TRACK_KEY, id || "");
    renderTracks();
    renderTrackBanner();
    markRelatedTasks();
    if (state.track && window.lrcLoadTopics) {
      window.lrcLoadTopics({ q: (state.track.jdKeywords || [])[0] || state.track.name });
    }
  }

  function initJobTimeline() {
    const host = document.getElementById("lrcJobTimeline");
    if (host) {
      host.replaceChildren();
      (CAREER.jobTimeline || []).forEach((item) => {
        const box = el("div", "lrc-timeline-item");
        box.append(
          el("strong", "", item.phase || ""),
          el("p", "", "目标：" + (item.goal || "")),
          el("p", "", "交付：" + (item.deliverable || "")),
          el("p", "", "验收：" + (item.checkpoint || ""))
        );
        host.append(box);
      });
    }
    const tips = document.getElementById("lrcResumeTips");
    if (tips) {
      tips.replaceChildren();
      (CAREER.resumeTips || []).forEach((text) => tips.append(el("li", "", text)));
    }
    const interview = document.getElementById("lrcInterview");
    if (interview) {
      interview.replaceChildren();
      (CAREER.commonInterview || []).forEach((text) => interview.append(el("li", "", text)));
    }
  }

  function initTracks() {
    const saved = readLocal(TRACK_KEY, "");
    state.track = TRACKS.find((track) => track.id === saved) || null;
    renderTracks();
    renderTrackBanner();
    markRelatedTasks();
    initJobTimeline();
  }

  /* ── 硬件价格表 ─────────────────────────────────────────────────────── */
  const TIER_LABEL = { zero: "零成本", starter: "入门", core: "核心配置", pro: "真机 / 高价" };

  function priceText(item) {
    if (item.priceRange) return item.priceRange;
    if (typeof item.priceCny === "number" && item.priceCny > 0) return "¥" + item.priceCny.toLocaleString("zh-CN");
    if (item.priceCny === 0) return "免费 / ¥0";
    if (typeof item.priceUsd === "number" && item.priceUsd > 0) return "$" + item.priceUsd.toLocaleString("en-US");
    return "暂无公开报价";
  }

  function hwRow(item) {
    const row = el("div", "lrc-hw-row");
    const name = el("div", "lrc-hw-name", item.name || "");
    name.append(el("span", "lrc-hw-cat", (item.category || "") + " · " + (TIER_LABEL[item.tier] || item.tier || "")));
    const price = el("div", "lrc-hw-price", priceText(item));
    price.append(el("small", "", "核验 " + (item.verifiedAt || "")));
    const info = el("div", "lrc-hw-info");
    info.append(el("div", "", (item.spec || "") + " ｜ 适合：" + (item.forWho || "")));
    info.append(el("div", "", (item.note || "") + " ｜ 来源：" + (item.source || "")));
    if (item.url && /^https:\/\//.test(item.url)) info.append(externalLink(item.url, "查看报价来源 ↗"));
    const actions = el("div", "lrc-track-actions");
    actions.append(composeLink("报个价 / 纠错", "price", {
      lines: [
        "设备：" + (item.name || ""), "页面标价：" + priceText(item),
        "核验时点：" + (item.verifiedAt || ""), "来源：" + (item.source || ""),
      ],
      titleSuffix: String(item.name || "").slice(0, 16), tags: ["硬件报价"],
    }));
    row.append(name, price, info, actions);
    return row;
  }

  function renderHardware() {
    const host = document.getElementById("lrcHardwareTable");
    const empty = document.getElementById("lrcHardwareEmpty");
    if (!host) return;
    const list = HARDWARE.filter((item) => {
      if (state.hwTier !== "all" && item.tier !== state.hwTier) return false;
      if (!state.hwNeedle) return true;
      const haystack = ((item.name || "") + (item.category || "") + (item.spec || "") + (item.forWho || "")).toLowerCase();
      return haystack.indexOf(state.hwNeedle) !== -1;
    });
    host.replaceChildren();
    list.forEach((item) => host.append(hwRow(item)));
    if (empty) empty.hidden = list.length > 0;
  }

  function initHardware() {
    const note = document.getElementById("lrcPriceNote");
    if (note && DATA.hardware) {
      note.textContent = "共 " + HARDWARE.length + " 项 · 核验时点 " + (DATA.hardware.updatedAt || "")
        + " · " + (DATA.hardware.fxNote || "") + "。含税、运费与套件口径逐条写在说明里，选型前请点开来源复核；「起售价」常常是不能二次开发的展示版。";
    }
    const filters = document.getElementById("lrcHardwareFilters");
    if (filters) {
      filters.addEventListener("click", (event) => {
        const chip = event.target.closest("[data-hw-tier]");
        if (!chip) return;
        state.hwTier = chip.dataset.hwTier;
        filters.querySelectorAll(".lrc-chip").forEach((item) => item.classList.toggle("is-active", item === chip));
        renderHardware();
      });
    }
    const search = document.getElementById("lrcHardwareSearch");
    if (search) search.addEventListener("input", () => {
      state.hwNeedle = search.value.trim().toLowerCase();
      renderHardware();
    });
    renderHardware();
  }

  /* ── 行业动态：服务端有数据就用实时，否则明确标注为调研快照 ───────────
     通用信源（科技媒体、厂商博客、arXiv）会混进与机器人无关的内容，
     所以实时条目在前端再做一次轻量相关性筛选，并按信源补出可读类别。
     ───────────────────────────────────────────────────────────────────── */
  const EMBODIED_NEWS_RE = /robot|embodied|\bvla\b|lerobot|isaac|mujoco|manipulat|humanoid|grasp|locomotion|dexterous|sim2real|teleop|slam|机器人|具身|机械臂|人形|遥操作|灵巧手|抓取|运动控制|仿真|模仿学习|强化学习/i;

  function apiNewsKind(item) {
    const label = String(item.category_label || "").trim();
    if (label) return label;
    const slug = (item.source && item.source.slug) || "";
    if (/releases/i.test(slug) || /github\.com/i.test(item.url || "")) return "开源";
    if (/arxiv/i.test(slug)) return "论文";
    return "资讯";
  }

  function isEmbodiedNews(item) {
    const hay = [
      item.title, item.summary, (item.source && item.source.name) || "",
      item.upstream_name, item.url,
    ].join(" ");
    return EMBODIED_NEWS_RE.test(hay);
  }

  function normalizeNews(item, fromApi) {
    return {
      date: fromApi ? String(item.published_at || "").slice(0, 10) : (item.date || ""),
      title: item.title || "未命名动态",
      summary: item.summary || "",
      source: fromApi ? ((item.source && item.source.name) || item.upstream_name || "社区动态库") : (item.source || ""),
      url: item.url || "",
      kind: fromApi ? apiNewsKind(item) : (item.kind || "动态"),
    };
  }

  function newsItem(item) {
    const box = el("article", "lrc-news-item");
    const top = el("div", "lrc-news-top");
    top.append(el("span", "lrc-news-date", item.date || "日期未标"), el("span", "lrc-news-kind", item.kind));
    box.append(top);
    if (item.url && /^https:\/\//.test(item.url)) {
      const link = el("a", "lrc-news-title", item.title);
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      box.append(link);
    } else {
      box.append(el("div", "lrc-news-title", item.title));
    }
    if (item.summary) box.append(el("p", "lrc-news-summary", item.summary));
    const foot = el("div", "lrc-news-foot");
    foot.append(el("span", "", "来源：" + item.source));
    foot.append(composeLink("带这条去讨论", "news", {
      lines: ["动态：" + item.title, "日期：" + (item.date || ""), "原文：" + (item.url || ""), "来源：" + item.source],
      titleSuffix: String(item.title).slice(0, 18), tags: ["行业动态"],
    }));
    box.append(foot);
    return box;
  }

  // 实时条目大多是英文原题，零基础用户容易劝退。把中文调研速览单独放在
  // 实时列表上方，并明标时点，避免把旧快照伪装成今日新闻。
  function renderNewsBrief() {
    const card = document.getElementById("lrcNewsBriefCard");
    const host = document.getElementById("lrcNewsBrief");
    if (!card || !host) return;
    if (!state.newsFromApi || !NEWS_SEED.length) {
      card.hidden = true;
      return;
    }
    const meta = document.getElementById("lrcNewsBriefMeta");
    if (meta) meta.textContent = "下面 " + Math.min(3, NEWS_SEED.length) + " 条是 "
      + ((DATA.news && DATA.news.updatedAt) || "2026-11-05")
      + " 人工整理的中文要点；再往下才是信源实时抓取的原文（多为英文）。";
    card.hidden = false;
    host.replaceChildren();
    NEWS_SEED.slice(0, 3).forEach((item) => host.append(newsItem(normalizeNews(item, false))));
  }

  function renderNewsFilters() {
    const filters = document.getElementById("lrcNewsFilters");
    if (!filters) return;
    const counts = new Map();
    state.newsItems.forEach((item) => counts.set(item.kind, (counts.get(item.kind) || 0) + 1));
    // 只渲染实际存在的类别，避免「调研快照」与「实时抓取」两套数据下出现死按钮。
    const kinds = Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1]).slice(0, 8).map(([kind]) => kind);
    state.newsKind = "all";
    filters.replaceChildren();
    ["all"].concat(kinds).forEach((kind) => {
      const chip = el("button", "lrc-chip" + (kind === "all" ? " is-active" : ""),
        kind === "all" ? "全部" : kind + " " + counts.get(kind));
      chip.type = "button";
      chip.dataset.newsKind = kind;
      filters.append(chip);
    });
  }

  function renderNews() {
    const host = document.getElementById("lrcNews");
    if (!host) return;
    const list = state.newsItems.filter((item) => state.newsKind === "all" || item.kind === state.newsKind);
    host.replaceChildren();
    if (!list.length) {
      host.append(el("p", "lrc-inline-notice", state.newsKind === "all"
        ? "暂无动态。"
        : "这个分类下暂时没有条目，切回「全部」看看。"));
      return;
    }
    list.forEach((item) => host.append(newsItem(item)));
  }

  function initNewsSources() {
    const host = document.getElementById("lrcNewsSources");
    if (!host) return;
    host.replaceChildren();
    NEWS_SOURCES.forEach((source) => {
      const row = el("div", "lrc-source-row");
      const left = el("div");
      if (source.siteUrl && /^https:\/\//.test(source.siteUrl)) {
        left.append(externalLink(source.siteUrl, source.name));
      } else {
        left.append(el("span", "", source.name || ""));
      }
      left.append(el("div", "lrc-source-note", String(source.feedKind || "").toUpperCase()
        + " · " + (source.cadence || "") + " · " + (source.language === "zh" ? "中文" : "英文")));
      row.append(left, el("span", "lrc-source-tag", source.feedKind === "api" ? "待接入" : "抓取中"));
      host.append(row);
    });
  }

  async function initNews() {
    const meta = document.getElementById("lrcNewsMeta");
    let items = [];
    try {
      const res = await fetch(NEWS_API);
      const data = await res.json().catch(() => ({}));
      if (res.ok && Array.isArray(data.items) && data.items.length) {
        const relevant = data.items.filter(isEmbodiedNews);
        const picked = relevant.length ? relevant : data.items;
        items = picked.slice(0, 24).map((item) => normalizeNews(item, true));
        state.newsFromApi = true;
        if (meta) meta.textContent = "来自社区动态库 · " + items.length + " 条"
          + (relevant.length ? "（已按机器人相关性筛选）" : "")
          + " · 服务端每 30 分钟抓取 · 最近响应 "
          + String(data.server_time || "").slice(0, 16).replace("T", " ");
      }
    } catch (_) { /* 落到调研快照 */ }
    if (!items.length) {
      items = NEWS_SEED.map((item) => normalizeNews(item, false));
      state.newsFromApi = false;
      if (meta) meta.textContent = "调研快照（" + ((DATA.news && DATA.news.updatedAt) || "2026-11-05") + "）· "
        + items.length + " 条 · 动态库还没有条目，抓取任务跑起来后会自动切换成实时内容";
    }
    state.newsItems = items;
    renderNewsBrief();
    renderNewsFilters();
    renderNews();
    initNewsSources();
    const filters = document.getElementById("lrcNewsFilters");
    if (filters) filters.addEventListener("click", (event) => {
      const chip = event.target.closest("[data-news-kind]");
      if (!chip) return;
      state.newsKind = chip.dataset.newsKind;
      filters.querySelectorAll(".lrc-chip").forEach((item) => item.classList.toggle("is-active", item === chip));
      renderNews();
    });
  }

  /* ── 学习打卡：写进碎碎念「提灯夜行」频道 ───────────────────────────── */
  function openCheckin(prefix) {
    if (!requireLogin("打卡，登录后同路人才能看到")) return;
    // 打卡表单在 #community 板块里；单板块视图下必须先切路由，否则表单是隐藏的。
    const section = document.getElementById("community");
    if (currentRoute() !== "community") goToRoute("community");
    else if (section) section.scrollIntoView({ behavior: "smooth", block: "start" });
    const form = document.getElementById("lrcCheckinForm");
    const text = document.getElementById("lrcCheckinText");
    if (form) form.hidden = false;
    if (text) {
      if (prefix && !text.value) text.value = "D?｜" + prefix + "｜";
      text.focus({ preventScroll: true });
    }
  }

  function checkinItem(item) {
    const box = el("div", "lrc-checkin-item");
    const content = String(item.content || "").replace(CHECKIN_TAG, "").trim();
    box.append(el("div", "", content || "（无正文）"));
    const author = item.author && (item.author.display_name || item.author.username)
      ? (item.author.display_name || item.author.username) : "社区成员";
    const meta = el("div", "lrc-checkin-meta");
    meta.append(
      el("span", "", author),
      el("span", "", String(item.created_at || "").slice(0, 10)),
      el("span", "", (item.like_count || 0) + " 赞"),
      el("span", "", (item.comment_count || 0) + " 评论")
    );
    box.append(meta);
    return box;
  }

  async function loadCheckins() {
    const host = document.getElementById("lrcCheckins");
    if (!host) return;
    try {
      const res = await fetch("/api/murmurs?channel=growth&q=" + encodeURIComponent(CHECKIN_TAG));
      const data = await res.json().catch(() => ({}));
      const items = Array.isArray(data.items) ? data.items : [];
      host.replaceChildren();
      if (!items.length) {
        host.append(el("p", "lrc-inline-notice", "还没有人打卡。今天的第一条会很有用：写下你卡在哪，比写「学完了」更帮助别人。"));
        return;
      }
      items.slice(0, 8).forEach((item) => host.append(checkinItem(item)));
    } catch (_) {
      host.replaceChildren(el("p", "lrc-inline-notice", "打卡流暂时不可用，稍后再看。"));
    }
  }

  function initCheckins() {
    const btn = document.getElementById("lrcCheckinBtn");
    const form = document.getElementById("lrcCheckinForm");
    const cancel = document.getElementById("lrcCheckinCancel");
    const submit = document.getElementById("lrcCheckinSubmit");
    const text = document.getElementById("lrcCheckinText");
    const hint = document.getElementById("lrcCheckinHint");
    if (btn) btn.addEventListener("click", () => openCheckin(""));
    const jump = document.getElementById("lrcCheckinJump");
    if (jump) jump.addEventListener("click", () => openCheckin(""));
    if (cancel) cancel.addEventListener("click", () => {
      if (form) form.hidden = true;
      if (hint) hint.textContent = "";
    });
    if (submit) submit.addEventListener("click", async () => {
      if (!requireLogin("打卡，登录后同路人才能看到")) return;
      const value = (text && text.value ? text.value : "").trim();
      if (!value) {
        if (hint) hint.textContent = "写一句今天的进展或卡点再发。";
        return;
      }
      const content = CHECKIN_TAG + " " + value;
      if (content.length > 1000) {
        if (hint) hint.textContent = "太长了，请精简到 1000 字以内。";
        return;
      }
      submit.disabled = true;
      try {
        await api("/api/murmurs", {
          method: "POST",
          body: JSON.stringify({
            content: content,
            channel: "growth",
            client_key: "lrc-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8),
          }),
        });
        if (text) text.value = "";
        if (form) form.hidden = true;
        if (hint) hint.textContent = "";
        toast("打卡成功，同路人能看到啦");
        loadCheckins();
      } catch (error) {
        if (hint) hint.textContent = error.message;
      } finally {
        submit.disabled = false;
      }
    });
    loadCheckins();
  }

  /* ── 左侧路由：每个板块一个 hash，一次只渲染一个板块 ──────────────────
     /forum/lrobotcup#hardware 可直接分享；浏览器前进/后退、手动改地址栏
     都能还原对应板块。无 JS 时不隐藏任何 section，链接退化为普通锚点。  */
  const ROUTE_DEFAULT = "start";
  const ROUTE_ALL = "all";

  function routeLinks() {
    return Array.from(document.querySelectorAll(".lrc-side-link[data-route]"));
  }
  function routeIds() { return routeLinks().map((link) => link.dataset.route); }
  function routeLabel(route) {
    const link = routeLinks().find((item) => item.dataset.route === route);
    return link ? link.textContent.replace(/^\d+/, "").trim() : "专题";
  }
  function decodeRoute(value) {
    try { return decodeURIComponent(value || "").trim(); } catch (_) { return ""; }
  }
  function currentRoute() {
    const route = decodeRoute(location.hash.replace(/^#/, ""));
    if (route === ROUTE_ALL) return ROUTE_ALL;
    return routeIds().includes(route) ? route : ROUTE_DEFAULT;
  }
  function scrollToLayout(behavior) {
    const layout = document.getElementById("lrcLayout");
    if (!layout) return;
    const top = Math.max(0, layout.getBoundingClientRect().top + window.scrollY - 72);
    window.scrollTo({ top: top, behavior: behavior || "auto" });
  }

  function applyRoute(options) {
    const opts = options || {};
    const route = currentRoute();
    const all = route === ROUTE_ALL;
    const ids = routeIds();
    if (!all) state.lastRoute = route;

    document.body.classList.toggle("lrc-allmode", all);
    const sections = Array.from(document.querySelectorAll(".lrc-article > section.lrc-section"));
    sections.forEach((section) => { section.hidden = !all && section.id !== route; });

    let activeIndex = -1;
    routeLinks().forEach((link, index) => {
      const active = !all && link.dataset.route === route;
      if (active) activeIndex = index;
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });

    const hint = document.getElementById("lrcRouteHint");
    if (hint) hint.textContent = all
      ? "通读模式：12 个板块全部展开；点左侧任意板块回到单页视图。"
      : "当前：" + routeLabel(route) + " · 地址栏可分享，前进/后退也能用。";
    const toggle = document.getElementById("lrcAllToggle");
    if (toggle) {
      toggle.setAttribute("aria-pressed", all ? "true" : "false");
      toggle.textContent = all ? "回到单页" : "通读全部";
    }
    const prev = document.getElementById("lrcPrevRoute");
    const next = document.getElementById("lrcNextRoute");
    if (prev && next) {
      prev.disabled = all || activeIndex <= 0;
      next.disabled = all || activeIndex < 0 || activeIndex >= ids.length - 1;
      prev.textContent = "← " + (activeIndex > 0 ? routeLabel(ids[activeIndex - 1]) : "上一板块");
      next.textContent = (activeIndex >= 0 && activeIndex < ids.length - 1
        ? routeLabel(ids[activeIndex + 1]) : "下一板块") + " →";
    }
    document.title = "LRobotcup · " + (all ? "全部板块" : routeLabel(route)) + " | KFlow 社区";
    if (opts.scroll) requestAnimationFrame(() => {
      // 无 hash = 默认板块 + 首屏，必须留在 hero；有 hash 才定位到两栏布局顶部。
      // 后退回到无 hash 的那一帧也要回顶，否则会停在上一板块的滚动位置。
      if (!location.hash) window.scrollTo({ top: 0, behavior: opts.smooth ? "smooth" : "auto" });
      else scrollToLayout(opts.smooth ? "smooth" : "auto");
    });
    return route;
  }

  function goToRoute(route, options) {
    const hash = "#" + encodeURIComponent(route);
    if (location.hash !== hash) {
      history.pushState({ lrcRoute: route }, "", location.pathname + location.search + hash);
    }
    applyRoute(Object.assign({ scroll: true }, options || {}));
  }
  window.lrcGoTo = goToRoute;

  function initRouter() {
    if (!routeLinks().length) return;
    // hash 路由自己决定滚到哪里；交给浏览器恢复会把「上次滚到某板块」的
    // 位置套到另一个板块上，刷新后直接跳过 hero。
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    // 首屏绝不能补写 #start：Chrome 在 load 之后仍会按 URL fragment 把
    // section#start 滚到视口顶部，hero 会被整个跳过去。无 hash 就是默认
    // 板块，地址栏干净同样可分享，点任意板块后才由 pushState 写入 hash。
    const hadHash = !!location.hash;
    const hashValue = decodeRoute(location.hash.replace(/^#/, ""));
    if (hadHash && hashValue !== ROUTE_ALL && !routeIds().includes(hashValue)) {
      // 外部锚点 / 拼错的板块：清成干净 URL，别让地址栏挂着不存在的路由。
      history.replaceState({ lrcRoute: ROUTE_DEFAULT }, "",
        location.pathname + location.search);
    }
    applyRoute({ scroll: hadHash && !!location.hash });

    // 页面内所有 #route 链接（hero、自测结果、底部 CTA）统一走路由。
    document.addEventListener("click", (event) => {
      const link = event.target.closest && event.target.closest('a[href^="#"]');
      if (!link) return;
      const route = decodeRoute(link.getAttribute("href").slice(1));
      if (route !== ROUTE_ALL && !routeIds().includes(route)) return;
      event.preventDefault();
      goToRoute(route);
    });

    const toggle = document.getElementById("lrcAllToggle");
    if (toggle) toggle.addEventListener("click", () => {
      goToRoute(currentRoute() === ROUTE_ALL ? (state.lastRoute || ROUTE_DEFAULT) : ROUTE_ALL);
    });
    const ids = routeIds();
    const prev = document.getElementById("lrcPrevRoute");
    const next = document.getElementById("lrcNextRoute");
    if (prev) prev.addEventListener("click", () => {
      const index = ids.indexOf(currentRoute());
      if (index > 0) goToRoute(ids[index - 1]);
    });
    if (next) next.addEventListener("click", () => {
      const index = ids.indexOf(currentRoute());
      if (index >= 0 && index < ids.length - 1) goToRoute(ids[index + 1]);
    });

    window.addEventListener("popstate", () => applyRoute({ scroll: true }));
    // 手动修改地址栏 hash 时不会触发 popstate，需要 hashchange 兜底。
    window.addEventListener("hashchange", () => applyRoute({ scroll: true }));
  }

  /* ── 目录高亮：通读模式下跟随滚动，单板块模式由路由接管 ────────────── */
  function initSectionObserver() {
    const links = routeLinks();
    const sections = links.map((link) => document.getElementById(link.dataset.route)).filter(Boolean);
    if (!("IntersectionObserver" in window) || !sections.length) return;
    const observer = new IntersectionObserver((entries) => {
      if (!document.body.classList.contains("lrc-allmode")) return;
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        links.forEach((link) => link.classList.toggle("is-active", link.dataset.route === entry.target.id));
      });
    }, { rootMargin: "-88px 0px -70% 0px", threshold: 0 });
    sections.forEach((section) => observer.observe(section));
  }

  function init() {
    initRouter();
    renderRoles();
    initQuiz();
    initGlossary();
    initPortfolio();
    initTracks();
    initStages();
    initProgress();
    initProjects();
    initResources();
    initTemplates();
    initTopics();
    initHardware();
    initNews();
    initCheckins();
    initSectionObserver();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
