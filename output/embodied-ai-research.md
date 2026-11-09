# 具身智能（Embodied AI / 机器人学习）入行知识与能力调研报告

> **调研时间**：2026 年 11 月 5 日
> **调研方式**：WebSearch / WebFetch 多轮检索，优先 2025–2026 年资料；关键链接已用 WebFetch 直连验证或以搜索引擎索引结果交叉确认（见文末「链接验证说明」）
> **标注体系**：`【事实】` = 有来源可查的客观信息；`【建议】` = 本报告给出的判断与学习建议；`【易变】` = 价格 / 版本号 / 模型名称 / 薪资等随时间变化，已附来源与时间，使用前请复核
> **适用对象**：准备进入具身智能方向的本科生、研究生、转行开发者、内容/课程设计者

---

## 0. 一页速览（专题页导语卡片）

- **这个领域在做什么 【事实】**：把大语言模型 / 视觉语言模型的能力「装进」物理实体，让机器人完成「看 + 懂指令 + 输出动作」的闭环。招聘 JD 里最高频的技术词是 **VLA、世界模型、模仿学习、强化学习、Sim2Real、多模态融合**。（来源：珞石机器人、纽鼐机器人、意界智创等 2026 年招聘页）
- **岗位分四条线 【事实】**：① 算法层（VLA / 世界模型 / RL / 运控 / SLAM / 感知）；② 硬件与系统工程层（关节模组、嵌入式、C++、系统集成）；③ 产品与商业化层；④ 应用操作层（数据采集员、部署调试）。（来源：2026 具身智能人才报告，三个皮匠报告 / 华博咨询）
- **最稀缺的人 【事实 + 建议】**：报告原文是「懂算法的不懂本体、懂机械的不懂大模型」的能力断层，缺的是「能把大模型装进机器人身体并让它干活」的人。【建议】因此不要只学单一栈，至少要能打通「数据 → 训练 → 部署 → 真机」一条完整链路。
- **最低入门成本 【易变】**：约 **100–500 美元**（LeRobot SO-101 机械臂，2025-04 发布）；零成本路径是纯仿真 + 公开数据集（Hugging Face Robotics Course 明确「no hardware required」）。
- **最权威的免费学习主线 【事实】**：`Robot Learning: A Tutorial`（Hugging Face × 牛津，arXiv:2510.12403，2025-10）→ 配套 LeRobot 代码；`CS 285`（UC Berkeley，2026 春季在授）；`Modern Robotics` 教材 + Coursera 专项课。

---

## 1. 岗位与行业现状（2025–2026）

### 1.1 六大岗位方向 · 能力要求 · 招聘关键词（可直接做成 6 张卡片）

| # | 岗位方向 | 典型职责 | 硬性能力要求（JD 原文提炼） | 高频招聘关键词 |
|---|---|---|---|---|
| 1 | **VLA / 具身大模型算法** | 端到端多模态具身大模型研发；跨本体预训练 / 微调 / 部署；动作 token 化 | 硕士+；精通 Python / PyTorch；深入理解 Transformer；VLM/VLA/世界模型；扩散模型 / 流匹配；大模型预训练 / 微调 / 分布式训练（Deepspeed / FSDP） | `VLA` `VLM` `OpenVLA` `π0/π0.5` `GR00T` `RDT` `World Model` `Action Token` `LoRA` `FSDP` |
| 2 | **机器人控制 / 运控（小脑）** | 人形 / 四足全身运动控制 WBC、力控 / 柔顺控制、灵巧操作 | 运动学与动力学、ROS/ROS2、RL/IL 策略训练、阻抗/导纳控制、MPC | `WBC` `PPO/SAC` `Sim2Real` `MPC` `阻抗控制` `力控` |
| 3 | **强化学习 / 模仿学习算法** | 具身操作任务的 RL 策略；真机强化学习；离线 RL | PPO / SAC / BC / DAgger / 离线 RL；仿真或真机训练经验；奖励曲线分析 | `PPO` `SAC` `Behavior Cloning` `DAgger` `Offline RL` `HIL-SERL` |
| 4 | **仿真与数据 / Sim2Real** | 仿真环境搭建、合成数据生成、数字孪生、系统辨识 | Isaac Sim / Isaac Lab / MuJoCo / Gazebo / SAPIEN；刚体动力学；执行器建模；域随机化 | `Isaac Sim` `Isaac Lab` `MuJoCo` `Domain Randomization` `System ID` `合成数据` |
| 5 | **部署 / 工程化 / 机器人系统** | 模型量化、推理加速、嵌入式部署、系统联调 | C++ / Linux / Python；ONNX / TensorRT；模型量化 INT8/INT4；ROS2 中间件、runtime、实时通信 | `C++` `Linux` `ROS2` `TensorRT` `ONNX` `EtherCAT` `CAN FD` `嵌入式` |
| 6 | **SLAM / 感知 / 3D 视觉** | 定位建图、6D 位姿估计、点云处理、多传感器融合 | 3D 视觉、点云滤波/分割/配准、PnP/EPnP、LiDAR、多传感器融合、手眼标定 | `SLAM` `6D Pose` `Point Cloud` `多传感器融合` `手眼标定` |

> **【事实·来源】** 上表能力要求取自：燕山大学就业网转载的珞石机器人「具身算法工程师」JD（2026-08 发布）、中科大就业网纽鼐机器人（杭州）「具身智能算法工程师」JD（2026-10-09）、猎聘「具身智能(VLA)技术专家」（意界智创 Enacta AI，2026-10 更新）、智联招聘具身智能算法岗、CSDN DAMO 开发者矩阵《机器人行业招聘 | 一批具身智能核心岗位正在开放》。
> **【事实】** 中科大那份 JD 的加分项写得很具体：在 **CoRL / RSS / ICRA / IROS / NeurIPS / ICML / ICLR / CVPR** 有论文（含在投 / workshop），或**复现过 OpenVLA、RDT**。

### 1.2 代表公司 / 团队 / 开源生态（2025–2026 公开招聘与报道中出现）

- **国内本体与创业公司** 【事实】：宇树科技 Unitree、智元机器人、优必选、魔法原子、珞石机器人 ROKAE、乐聚机器人、小米机器人、蚂蚁集团具身智能、光轮智能（Sim2Real）、意界智创 Enacta AI、纽鼐机器人（Neura Robotics 杭州）。
- **国内研究机构 / 开源生态** 【事实】：北京智源人工智能研究院（RoboBrain 2.0）、北京人形机器人创新中心、北京通用人工智能研究院、上海人工智能实验室（CogACT）、清华大学（RDT-1B，与 Spirit AI）、南京大学 LoongGroup（世界模型综述）、DataWhale、Xbotics 具身智能社区。
- **国际** 【事实】：Google DeepMind（RT-2 / Gemini Robotics）、Physical Intelligence（π0 / π0.5 / openpi）、NVIDIA（Isaac Sim / Isaac Lab / GR00T）、Hugging Face（LeRobot / SmolVLA / Pollen Robotics）、Stanford / UC Berkeley / Toyota Research Institute（ACT / Diffusion Policy / OpenVLA / Octo）、Meta（V-JEPA 2）、Oxford（VLA 综述、Robot Learning Tutorial）。
- **【建议】** 做求职或选题时，按「本体厂 / 算法模型厂 / 数据与仿真厂 / 开源框架方」四分法去定位公司，比按「人形 or 机械臂」分类更贴近真实招聘结构。

### 1.3 人才供需与薪资（`【易变】` 全部附来源与时间）

| 指标 | 数值 | 来源与时间 |
|---|---|---|
| 具身智能领域招聘指数 | 2026 年 1–4 月为 **579**，2025 年同期 36，**约 15 倍** | 脉脉高聘人才智库，经今日头条《具身智能抢人大战》与三个皮匠报告转引，2026 |
| 人形机器人新发职位 | 同比 **+215.8%**，平均年薪 **40.61 万元** | 猎聘大数据，经同上转引，2026 |
| 行业平均招聘年薪 | **33.34 万元**（AI 行业 29.09 万；人形机器人赛道 40.61 万） | 三个皮匠报告《2026 具身智能人才报告》（华博咨询），2026 |
| 算法工程师同比增幅 | **+70.70%**，居机器人领域第一 | 今日头条《具身智能抢人大战》，2026 |
| 人才缺口 | 业内预计约 **100 万人**；人社部拟新增「具身智能机器人应用技术员」 | 三个皮匠报告，2026 |
| 真机强化学习算法工程师 | 智元 **80K·15 薪**（年薪最高约 120 万），工作年限仅 1–3 年 | 腾讯新闻《年薪百万招 0 工作经验工程师》，2026-03-19 |
| 应届具身智能算法岗 | 智元最高 **80K·16 薪**（约 128 万）；魔法原子 VLA/VLM 岗最多 120 万年薪 | 同上，2026-03-19 |
| 深度强化学习算法工程师 | 宇树科技标注「热招/急招」**4–7 万/月**；魔法原子 **50–70K·15 薪** | 同上，2026-03-19 |
| 数据采集员 / 应用操作层 | 日薪 **200–250 元**，全职月薪 **4000–8000 元** | 三个皮匠报告，2026 |

> **【事实】** 多篇报道共同指向「算法溢价」：万联证券研报观点认为软件与算法是人形机器人规模化应用的主要挑战；工程类岗位多在 20–40K·15 薪，明显低于算法岗。
> **【建议 / 风险提示】** 上述薪资来自招聘平台与媒体转引，**存在个例、总包含股权、标题党放大**等因素，且 2026 年市场波动快；专题页若引用，建议统一标注「媒体报道，非官方统计，2026 年」并避免写成「平均薪资」。

### 1.4 教育与政策信号（`【易变】`）

- **【事实】** 据三个皮匠报告转引：2026 年 4 月教育部新版本科目录首次在「交叉学科」门类列入 **「具身智能」专业**，9 所「双一流」高校首批招生（北京理工大学 120 人、北航 30 人）；职业教育新增职业本科「具身智能工程技术」与高职专科「具身智能机器人技术」；首批本科生 **2030 年**毕业，2026–2029 为供给空窗期。人才培养区域呈「京深杭沪」四极。
- **【建议】** 这条对「现在入行」是正向信号：未来 3–4 年科班供给仍不足，非科班通过开源项目 + 作品集切入仍有窗口。但教育目录信息请以教育部官方文件复核后再上线。

---

## 2. 知识栈分层（重点 · 可拆成学习路线卡片）

> **分层原则 【建议】**：L0→L1 是「能不能和机器人对话」，L2→L3 是「能不能让机器人学」，L4→L5 是「能不能做出 2025–2026 年一线水平的工作」。每层都给出**验收标准**，方便做成进度卡片。

### L0 · 数学与编程基础

| 项 | 内容 |
|---|---|
| **数学** | 线性代数（矩阵/特征值/奇异值分解/李群与李代数初步）、概率论与统计、多元微积分、最优化（梯度下降、凸优化、拉格朗日乘子） |
| **编程** | Python（NumPy / Pandas / Matplotlib / 面向对象）、C++（工程/嵌入式/底层岗必备）、Linux（Ubuntu 22.04/24.04、shell、环境变量、权限）、Git（clone / branch / PR）、Docker |
| **框架工具** | PyTorch、Git、Docker（DataWhale 学习路径把这三样列为「工程工具」） |
| **验收标准** | 能手写 NumPy 实现坐标变换与最小二乘；能独立在 Ubuntu 上配好 conda + PyTorch + CUDA 环境并把开源仓库跑通；能提一个有效 PR |
| **对应岗位** | 全岗位底座；工程/部署岗对 C++、Linux 要求最高 |

> **【事实】** 中科大转载的纽鼐机器人 JD 明确要求「扎实的数理基础（线性代数、概率论、优化方法）」；DataWhale 学习路径第一阶段（1–2 个月）把 Python / NumPy / C++ / PyTorch / Git / Docker 列为基础项。
> **【资源】** Modern Robotics 教材附录 D 即「Optimization and Lagrange Multipliers」；附录前有「Linear Algebra Review」练习。

### L1 · 机器人学基础

| 项 | 内容 |
|---|---|
| **刚体运动与建模** | 坐标变换、旋转表示（旋转矩阵 / 欧拉角 / 四元数 / 指数坐标）、螺旋理论、DH 参数、URDF |
| **运动学 / 动力学** | 正/逆运动学、速度运动学与静力学、雅可比、闭链运动学、开链动力学 |
| **控制与规划** | 轨迹生成（关节空间 / 笛卡尔空间）、运动规划、PID、阻抗/导纳控制、力控、MPC、WBC |
| **感知与标定** | 相机模型、RGB-D / 点云、IMU、力/力矩传感器、编码器、**手眼标定（eye-in-hand / eye-to-hand）**、PnP/EPnP 位姿估计、多传感器融合、TF 变换树 |
| **ROS2** | topic / service / action、节点生命周期、TF2、MoveIt 2、ros2_control、Nav2、Gazebo |
| **验收标准** | 能手推六轴机械臂（如 UR5）逆解；能用 ROS2 + MoveIt2 让仿真机械臂完成一次抓取；能把一个真实物体输出为「机器人坐标系下的位置 + 朝向」 |

> **【事实】** 珞石机器人 JD 要求「熟悉基础机器人学原理，如坐标变换、机械臂正/逆运动学、路径规划、轨迹规划」；《具身智能回理性期》一文给出五步走，并明确「我更愿意招一个把机械臂逆解推导得明明白白、但还不会用大模型的人，而不是反过来」。
> **【事实·版本】** ROS 2 发行版（**查阅 docs.ros.org，2026-11-05**）：最新 LTS 为 **Lyrical Luth**（官方推荐给所有用户）；**Jazzy Jalisco** 支持至 2029-05；**Humble Hawksbill** 至 2027-05；**Kilted Kaiju** 为非 LTS，官方横幅提示 **2026-11-30 EOL**；**Rolling Ridley** 为滚动版。新手教程入口 `docs.ros.org/en/lyrical/Tutorials.html`。**【建议】** 新项目优先 Jazzy 或 Lyrical，避开即将 EOL 的 Kilted。

### L2 · 机器学习 / 深度学习

| 项 | 内容 |
|---|---|
| **基础** | 神经网络、反向传播、训练/验证/测试闭环、过拟合与正则 |
| **架构** | CNN、ViT、Transformer、注意力机制、CLIP 类视觉-语言对齐、多模态融合 |
| **生成模型** | 扩散模型（DDPM 思路）、流匹配 Flow Matching、VAE/CVAE（ACT 用到）、动作 chunk |
| **工程** | 混合精度、分布式训练（FSDP / Deepspeed）、LoRA 微调、推理优化（量化 / ONNX / TensorRT / vLLM）、异步推理 |
| **验收标准** | 能独立用 PyTorch 从零训练一个小模型并画出损失曲线；能读懂 OpenVLA / π0 的架构图，说清「图像 token、语言 token、动作 token 各自怎么进网络」 |

> **【事实】** 多份 2026 年 JD 要求「理解 Transformer / 扩散模型等主流架构」「有大模型训练（预训练、微调、分布式训练）经验」「模型量化、硬件加速等嵌入式部署」。

### L3 · 强化学习与模仿学习

| 分支 | 必学算法 / 概念 |
|---|---|
| **RL 基础** | MDP（状态/动作/奖励/转移/折扣）、值函数、Q-learning、DQN、策略梯度 REINFORCE、Actor-Critic |
| **主流深度 RL** | **PPO、SAC**、DDPG、TD3、TRPO、GAE、model-based RL、离线 RL（Offline RL）、Offline-to-Online、探索、多任务 RL、控制即推断 |
| **模仿学习** | **行为克隆 BC**、**DAgger**（缓解分布偏移/复合误差）、GAIL / 逆强化学习、ACT（Action Chunking with Transformers）、Diffusion Policy、VQ-BeT |
| **机器人特有** | 真机 RL 的安全与样本效率、人在回路（HIL-SERL）、奖励设计、动作分块（action chunking）、Sim2Real |
| **工具** | Stable-Baselines3、RLlib（Ray）、Gymnasium、RoboMimic、MuJoCo Playground |
| **验收标准** | 用 SB3 在 Gymnasium 上训练 PPO/SAC 并解释奖励曲线；在 RoboMimic 或 LeRobot 上跑通 BC → ACT → Diffusion Policy 三种策略并对比成功率 |

> **【事实·课程验证】** UC Berkeley **CS 285 Deep Reinforcement Learning** 2026 春季在授（教师 **Sergey Levine**），作业为 HW1 模仿学习、HW2 策略梯度、HW3 Q-learning 与 Actor-Critic、HW4 LLM RL、HW5 离线 RL；25 讲覆盖 BC、策略梯度、DQN/SAC、高级策略梯度、控制即推断、Model-Based RL、Offline RL、探索、RL 理论、多任务 RL。（WebFetch 直连课程主页验证，2026-11-05）
> **【事实】** OpenAI **Spinning Up** 提供 VPG / TRPO / PPO / DDPG / TD3 / SAC 的理论讲解与实现，含 RL 入门三部分、关键论文清单与习题（WebFetch 验证）。
> **【事实】** `Robot Learning: A Tutorial` 指出：简单行为克隆的两大挑战是**复合误差**与**专家演示的多模态性**；ACT / Diffusion Policy 通过学习专家行为分布来建模多模态；Diffusion Policy 仅需 **50–150 条演示（约 15–60 分钟遥操作）** 即可训练；HIL-SERL 在真机上 **1–2 小时**可掌握复杂操作任务、成功率接近 100%。

### L4 · 具身智能前沿（VLA / 世界模型 / 数据集）

#### 4.1 VLA 代表性工作（`【易变】` 模型名称与参数量请复核原始论文）

| 模型 | 机构 / 时间 | 动作生成路线 | 关键事实 | 开源情况 |
|---|---|---|---|---|
| **RT-1 / RT-2** | Google DeepMind，2022 / 2023 | 自回归离散 token | RT-2 把动作当语言 token 联合训练，奠定 VLA 概念；55B PaLI-X / 12B PaLM-E 量级，1–5 Hz | **闭源、无公开权重**（RT-2 官方训练代码未开源） |
| **OpenVLA** | Stanford / UC Berkeley / TRI / Google DeepMind，2024 | 自回归离散 | **7B 参数**，基于 Prismatic-7B VLM（Llama 2 7B + DINOv2 + SigLIP）；在 **Open X-Embodiment 的 97 万条 episodes** 上训练；64×A100 训练 15 天 | 代码与权重全开源，支持单张消费级 GPU + LoRA 微调 |
| **Octo** | UC Berkeley 等，2024 | 扩散 | 在 OXE 约 80 万条轨迹上训练，9 个机器人平台验证，可在消费级 GPU 上数小时微调到新本体 | 开源 |
| **π0 / π0.5 / π\*0.6** | Physical Intelligence，2024-10 / 2025-04 / 后续 | **流匹配 Flow Matching**（连续动作） | π0：2.6B PaliGemma VLM + 300M 动作专家的 Mixture-of-Transformers，**50 Hz** 动作块，跨 7 种机器人构型；π0.5 引入跨本体 + 网页数据联合训练与高层语义子任务规划 | 训练代码 2025-02 以 **openpi** 开源 |
| **GR00T N1 / N1.5 / N1.7** | NVIDIA，2025-03 起 | 扩散 / 流匹配，快慢双系统 | System 2 VLM 约 10 Hz 理解环境，System 1 DiT 生成约 120 Hz 全身动作；面向人形机器人 | 代码开源（NVIDIA Open Model License 权重），依赖 NVIDIA 生态 |
| **SmolVLA** | Hugging Face，2025-06 | 流匹配，紧凑 VLA | **4.5 亿参数**，仅用 LeRobot 社区数据集预训练，内存约为 π0 的 1/7；SO-100 成功率由 51.7% → **78.3%** | 完全开源，适合消费级 GPU / 边缘设备 |
| **RDT-1B / CogACT / Gemini Robotics** | 清华 & Spirit AI / 上海 AI Lab / Google DeepMind，2025 | 扩散 / 认知与动作解耦 / 具身推理 | 双臂扩散大模型；Gemini Robotics 2025-03 发布，On-Device 版 2025-06（可本地运行、50–100 条演示适配新任务） | 部分开源 / 部分闭源 |

> **【事实·路线之争】** 2024–2025 年 VLA 分化为两条路线：**离散化自回归**（动作即语言，代表 OpenVLA，继承 LLM 推理能力但精度受离散化粒度限制、推理较慢）与**连续生成式**（扩散 / 流匹配，代表 Octo、π0、GR00T，动作平滑、适合高频控制）。最新趋势是**层级化架构**（高层语义子任务 + 底层连续动作，如 π0.5、GR00T N1）与**潜在动作学习**（从无标注人类视频学动作表示，如 LAPA、UniVLA）。来源：DAMO 开发者矩阵《2024-2025 年 VLA 模型前沿研究报告》《VLA 模型：概念、演进、代表工作与挑战》，2025。
> **【事实·微调效果】** OpenVLA-OFT 用并行解码 + 动作分块 + 连续动作表示 + L1 回归，推理速度提升 **25–50×**，在 LIBERO 四套任务上平均成功率 **97.1%**（项目页 openvla-oft.github.io）。

#### 4.2 世界模型与具身大模型

- **【事实】** 综述 `A Comprehensive Survey on World Models for Embodied AI`（arXiv:2510.16732，2025-10-19）提出**功能–时间–空间三轴**分类框架；回顾从 Ha & Schmidhuber 2018「World Models」到 Dreamer 系列，再到 Sora、Meta V-JEPA 2 的演进；指出三大挑战：数据与评估碎片化、计算效率瓶颈、建模策略固有矛盾。
- **【事实】** `A Survey: Learning Embodied Intelligence from Physical Simulators and World Models`（arXiv:2507.00917，v3 2025-09-03，南京大学等）系统梳理物理仿真器与世界模型如何共同弥合 Sim2Real，附带持续更新的文献仓库 `NJU3DV-LoongGroup/Embodied-World-Models-Survey`。
- **【建议】** 世界模型目前「术语未统一」，入门阶段读一篇综述建立坐标系即可，不必一上来追每篇新论文。

#### 4.3 机器人数据集（`【易变】` 规模口径不一，已列出差异）

| 数据集 | 规模 / 构成 | 定位 | 入口 |
|---|---|---|---|
| **Open X-Embodiment (OXE)** | 22 种机器人本体、60 个单实验室数据集、21 家机构；不同来源口径为 **16 万+ 演示 / 97 万 episodes / 100 万+ 轨迹 / v1.1 约 240 万轨迹（其中约 140 万为真机操作）** | 跨本体预训练事实标准，OpenVLA、Octo、RT-X 均基于此 | `github.com/google-deepmind/open_x_embodiment`、`robotics-transformer-x.github.io`；LeRobot 有转换版 collection |
| **DROID** | **76,000 条轨迹、564 个场景、18 套相同 Franka 臂**（Khazatsky et al., 2025） | 真实世界多样性、泛化基准 | `hf.co/datasets/lerobot/droid_1.0.1` |
| **BridgeData V2** | 约 6 万条桌面操作演示，UC Berkeley，WidowX | 单臂操作、微调常用 | 见 OXE / LeRobot Hub |
| **ALOHA / Mobile ALOHA** | 双臂遥操作，30+ 任务 | ACT 起源数据集，双臂模仿学习 | `tonyzhaozh.github.io/aloha` |
| **LeRobot Hub** | HF 社区数据集，检索时 HF 组织页显示 **189 个数据集、68 个模型**（2026-11，易变） | 格式统一、`lerobot` 标签一键下载，最适合练手 | `huggingface.co/lerobot` |
| **LIBERO / Meta-World** | 仿真基准 | 策略评测、VLA 微调标准基准 | `github.com/Lifelong-Robot-Learning/LIBERO` |

> **【事实·重要口径提醒】** 不要把 OXE 说成单一数字：原论文合集截至 2023 年的数据；LeRobot v0.4.0 博客提到 OXE 量级 **> 400 GB**、Datasets v3.0 为支持它做了分块式 Episode 与流式读取；OXE-AugE（2025-12）通过增强 16 个 OXE 子集得到 **440 万+ 轨迹**，作者报告微调 OpenVLA / π0 在未见本体上成功率提升 24–45%（作者自报结果，非独立基准）。
> **【事实·许可】** OXE 官方仓库声明：软件 Apache 2.0，其他材料 CC BY 4.0，且「not an official Google product」；商用需逐个数据集查看许可。

### L5 · 仿真与工程

| 仿真器 | 定位 | 适合练手的原因 | 许可 / 门槛 |
|---|---|---|---|
| **MuJoCo** | 接触丰富的操作任务「黄金标准」物理引擎 | 快、接触精确、RoboMimic / dm_control / MuJoCo Playground 生态成熟；有 4 个 Colab 教程的 `mujoco_playground` 尤其适合 RL 入门 | Apache 2.0（DeepMind 2022 起开源）；**CPU 可跑**，门槛最低 |
| **Isaac Sim + Isaac Lab** | GPU 并行 + 高保真传感器 / 合成数据 / 人形与四足 Sim2Real 工业标准 | 10,000+ 并行环境、16+ 机器人模型、30+ 预置环境；集成 RSL RL / skrl / RL Games / Stable-Baselines | **需要 RTX 显卡**；`【易变】` Isaac Lab **3.0.0 对应 Isaac Sim 6.2**，v2.3.X 对应 4.5/5.0/5.1（GitHub 官方兼容表，查阅 2026-11-05），BSD-3 许可 |
| **Gazebo** | ROS2 原生全系统仿真（传感器、导航、HIL） | 无真机时学 ROS2 的最佳搭配；与 ROS2 有固定配对（Jazzy↔Harmonic，Humble↔Fortress） | Apache 2.0；对硬件要求低 |
| **PyBullet** | 轻量快速原型 | 配置比 MuJoCo 更简单，适合教学 | zlib |
| **Habitat / Habitat-Lab / Habitat-Sim** | 具身导航、VLN、视觉语言导航 | 室内 3D 场景与 VLN-CE 基准 | Meta（facebookresearch） |
| **SAPIEN / RLBench / RoboSuite** | 操作任务仿真与基准 | 可复现的操作基准 | 开源 |

**工程化关键词**：域随机化（视觉随机化可激进、物理参数围绕实测值保守随机化）、系统辨识 System ID、数字孪生、动作 chunk、推理延迟（控制环 50–200 ms 延迟足以毁掉策略）、模型量化 INT8/INT4、TensorRT / ONNX、异步推理、真机安全（急停、限速、接触力约束）。

> **【事实·版本】** Isaac Lab 官方仓库（WebFetch 验证）：BSD-3 许可，多后端（Newton / OVRTX / OVPhysX / Isaac Sim），支持刚体、铰接系统、可变形物体，传感器含 RTX 相机 / LiDAR / 接触 / IMU；技术报告 arXiv:2511.04831（2025）。
> **【事实】** 第三方 2026-10-20 核对的版本：MuJoCo 3.15.0（2026-10-05）、Gazebo Jetty LTS（2025-09 发布，支持至 2031-05）、Isaac Lab 2.3.2 + Isaac Sim 5.1。**【建议】** 二手版本号仅作参考，安装前一律以官方发布页 / 兼容表为准，并**锁定版本 + 记录随机种子**。

---

## 3. 权威学习资源（含可点击 URL）

### 3.1 大学课程 / 公开课

| 课程 | 提供方 | 链接 | 验证 |
|---|---|---|---|
| **CS 285: Deep Reinforcement Learning**（2026 春季在授，Sergey Levine） | UC Berkeley | https://rail.eecs.berkeley.edu/deeprlcourse/ | ✅ WebFetch 已验证；含全部 slides / homeworks；Fall 2023 录像在 YouTube |
| **Spinning Up in Deep RL** | OpenAI | https://spinningup.openai.com/en/latest/ | ✅ WebFetch 已验证 |
| **Modern Robotics 专项课**（6 门：Foundations of Robot Motion / Robot Kinematics / Robot Dynamics / Robot Motion Planning and Control / Robot Manipulation and Wheeled Mobile Robots / Capstone） | Northwestern，Coursera | 入口见 http://lynchandpark.org/ 的「Online Courses」章节 | ✅ 教材主页 WebFetch 已验证（含 6 门课名称与 edX 两门 Robot Mechanics and Control） |
| **Hugging Face Robotics Course**（免费、**无需硬件**、纯仿真 + 公开数据集，约 30–45 分钟/单元） | Hugging Face | https://huggingface.co/learn/robotics-course/unit0/1 | ⚠️ 多个独立来源给出同一 URL；HF 域名 WebFetch 直连受限 |
| **从零开始学具身智能（Every-Embodied）** | DataWhale | https://www.datawhale.cn/ | ✅ 搜索结果确认；覆盖 Python → 机器人学 → 仿真 → CV → 运动规划 → RL → VLA，用 MuJoCo / LeRobot / OpenVLA / SmolVLA |
| **Dive into Embodied AI 学习路径**（基础 1–2 月 / 定向 2–3 月 / 项目持续；6 个项目） | DataWhale | https://datawhalechina.github.io/dive-into-embodied-ai/docs/overview/learning-path | ✅ WebFetch 已验证；仓库 https://github.com/datawhalechina/dive-into-embodied-ai |
| **李宏毅机器学习 / 生成模型 / 元学习** | 台大 | https://speech.ee.ntu.edu.tw/hylee/index.php | 多份中文学习路线引用 |
| **Xbotics 具身智能手册**（19 讲，从端到端、数据采集、模仿学习、Diffusion Policy、VLA 实操到 RL、VLN、Embodied Agent，附全部开源链接） | Xbotics 社区 | https://github.com/Xbotics-Embodied-AI-club/Xbotics-Embodied-AI-Handbook | ✅ 搜索结果确认 |

### 3.2 经典教材

| 教材 | 作者 / 出版 | 免费入口 | 用途 |
|---|---|---|---|
| **Modern Robotics: Mechanics, Planning, and Control** | Kevin M. Lynch & Frank C. Park，Cambridge University Press，2017（更新第一版预印本 2019-12） | http://lynchandpark.org/ （免费 PDF 预印本 + 视频 + 习题；中文版机械工业出版社） | 旋量理论 / 指数坐标；13 章覆盖位形空间→刚体运动→正逆运动学→动力学→轨迹生成→运动规划→控制→抓取→轮式机器人 |
| **Reinforcement Learning: An Introduction (2nd ed.)** | Sutton & Barto，MIT Press | http://incompleteideas.net/book/the-book-2nd.html （免费 PDF；配套代码 https://github.com/ShangtongZhang/reinforcement-learning-an-introduction） | RL 理论圣经 |
| **Probabilistic Robotics** | Thrun, Burgard & Fox | 部分高校图书馆提供 | SLAM / 概率感知（数学最密） |
| **Robotics, Vision and Control**（第 3 版 Python-first）、**Introduction to Robotics: Mechanics and Control**（Craig）、**Robotics: Modelling, Planning and Control**（Siciliano 等）、**The Robotics Primer**（Mataric，零基础） | — | — | 按层次选读；本科用 Craig / Niku，研究生用 Modern Robotics / Probabilistic Robotics |

### 3.3 综述 / 教程论文（优先读这几篇，2025 年新）

| 文献 | 链接 | 说明 |
|---|---|---|
| **Robot Learning: A Tutorial**（Capuano, Pascal, Zouitine, Wolf, Aractingi；2025-10-14；Hugging Face × 牛津） | https://arxiv.org/abs/2510.12403 | ✅ WebFetch 验证；从经典机器人学 → RL/BC → 生成模型 → 通用语言条件策略，附 LeRobot 可运行示例。**最推荐的第一篇通读材料** |
| **Vision-Language-Action Models for Robotics: A Review Towards Real-World Applications**（IEEE Access 2025, vol.13, pp.162467–162504, DOI 10.1109/ACCESS.2025.3609980） | https://vla-survey.github.io/ ｜ https://arxiv.org/abs/2510.07077 ｜ https://ieeexplore.ieee.org/document/11164279 | ✅ WebFetch 验证；含可筛选/排序的 VLA 模型交互表（按 Category / Task / Modality / Robot / Backbone） |
| **A Survey: Learning Embodied Intelligence from Physical Simulators and World Models**（v3 2025-09-03） | https://arxiv.org/abs/2507.00917v3 ｜ https://github.com/NJU3DV-LoongGroup/Embodied-World-Models-Survey | 仿真器 × 世界模型双主线 |
| **A Comprehensive Survey on World Models for Embodied AI**（2025-10-19） | https://arxiv.org/html/2510.16732v1 | 功能–时间–空间三轴分类 |
| **Sim-to-Real Transfer in Deep RL for Robotics: A Survey** | https://arxiv.org/abs/2009.13303 | Sim2Real 经典综述 |
| **OpenVLA** | https://arxiv.org/abs/2406.09246 ｜ https://openvla.github.io/ | ✅ WebFetch 验证 7B / 97 万 episodes / 64×A100×15 天 |
| **Diffusion Policy** | https://arxiv.org/abs/2303.04137 ｜ https://github.com/real-stanford/diffusion_policy | 扩散策略开山作 |
| **OpenVLA-OFT**（微调配方，LIBERO 97.1%） | http://openvla-oft.github.io/ | 进阶微调必读 |

### 3.4 官方文档

- ROS 2：https://docs.ros.org/ （新手教程 https://docs.ros.org/en/lyrical/Tutorials.html ）｜包索引 https://index.ros.org/ ｜Discourse https://discourse.ros.org/ ｜Robotics Stack Exchange https://robotics.stackexchange.com/
- Gazebo：https://gazebosim.org/docs/latest/getstarted/
- Gymnasium：https://gymnasium.farama.org/ （✅ WebFetch 验证：OpenAI Gym 的维护分支，Farama Foundation，提供 `env.reset()/env.step()` 标准 API 与迁移指南）
- Stable-Baselines3：https://github.com/DLR-RM/stable-baselines3 ｜ https://stable-baselines3.readthedocs.io/
- RoboMimic：https://github.com/ARISE-Initiative/robomimic ｜ https://robomimic.github.io/
- RLlib：https://github.com/ray-project/ray ｜ https://docs.ray.io/en/latest/rllib/index.html
- LeRobot：https://huggingface.co/docs/lerobot/index ｜ SO-101 指南 https://huggingface.co/docs/lerobot/so101 ｜ 仓库 https://github.com/huggingface/lerobot （✅ WebFetch 验证仓库存在，标题「Making AI for Robotics more accessible with end-to-end learning」）
- Isaac Lab 文档：https://isaac-sim.github.io/IsaacLab/main/
- OpenVLA 模型：https://huggingface.co/openvla

### 3.5 中文社区 / 公众号 / 专栏

- **【事实】** DataWhale（https://www.datawhale.cn/ ）、`Dive into Embodied AI`、Xbotics 具身智能手册 是本轮检索中结构化程度最高的三份中文免费学习路径。
- **【事实】** CSDN / DAMO 开发者矩阵（如「VLA 模型：概念、演进、代表工作与挑战」「基础差/零基础人员具身智能学习路线」「机器人行业招聘」）、CSDN 具身智能社区、机器之心公众号（例：HuggingFace 联合牛津 `Robot Learning: A Tutorial` 报道）、EmboX 具身工坊公众号（LeRobot 零门槛入门与 Push-T 实战）是中文资讯与实战解读的主要来源。
- **【事实】** 跨领域社区：ROSChina（中国机器人操作系统社区）、智源社区具身智能小组、古月居、知乎「具身智能 / 机器人学习」专栏、掘金，以及 B 站「RoboMimic 模仿学习」类视频教程；顶会风向标为 **ICRA / IROS / CoRL / RSS**，兼看 CVPR / NeurIPS / ICLR / ICML 机器人相关论文。
- **【建议】** 中文社区适合快速入门与排坑，但**模型参数、版本号、榜单数字务必回到论文 / 官方仓库核对**——本轮检索就发现同一数据集规模在不同中文文章里有 4 种口径。

### 3.6 竞赛

| 赛事 | 2025–2026 关键事实 | 来源 |
|---|---|---|
| **中国机器人大赛暨 RoboCup 机器人世界杯中国赛** | 2025-10-19 石家庄落幕；300 余所高校、近 1700 支队伍、5000+ 选手；大学组 24 大项；**首次增设「智源具身大模型挑战赛」**，为国家级赛事首个具身智能专项赛道，使用智源开源大模型 **RoboBrain 2.0** 考核「感知–认知–决策」闭环 | 科技日报 https://www.stdaily.com/web/gdxw/2025-10/20/content_418037.html ｜ 中国日报 https://cn.chinadaily.com.cn/a/202510/20/WS68f59b92a310c4deea5ed1c4.html |
| **中国机器人及人工智能大赛 · 人形机器人专项赛** | 2025-08-24 合肥，全国首个全尺寸人形机器人赛事；近 400 所高校 6000 余名学生，100 多所高校 200 余支队伍 320 多台人形机器人；机型覆盖 Kuavo / Roban / Aelos；引入具身智能、开源鸿蒙；已列入全国普通高等学校学科竞赛排行榜 | 中新网安徽 https://www.ah.chinanews.com.cn/news/2025/0824/336494.shtml |
| **RoboCup 国际** | **RoboCup 2026 首次由韩国主办（仁川）**，预计 3000+ 参与者；2026-07-05 官网报道仁川完成首场完整 **11 v 11 人形机器人足球赛**。联赛含 Soccer（KidSize / Standard Platform / Middle Size / Small Size / Humanoid）、Rescue、@Home、Industrial、Junior | https://www.robocup.org/ （✅ WebFetch 验证） |
| **其他可关注** | RoboMaster、Habitat / VLN 相关挑战、LIBERO / Meta-World 等仿真基准榜、Hugging Face LeRobot 全球黑客松（2025 年约 3000 人参与） | 综合来源 |

---

## 4. 开源项目与框架（定位 / 练手价值 / 硬件门槛）

| 项目 | 定位 | 为什么适合练手 | 硬件门槛 | 许可 / 备注 |
|---|---|---|---|---|
| **LeRobot** (HF) | 端到端机器人学习：数据集格式 + 策略 + 真机控制 + 评估一体 | **最佳第一站**。四步闭环「遥操作 → 录制 → 训练 → 部署」；Push-T 仿真任务零硬件；内置 ACT / Diffusion Policy / π0 / π0.5 / GR00T / SmolVLA | **零硬件可入门**（公开数据集 + 仿真）；真机用 SO-101 | Apache 2.0；PyTorch；v0.4.0 起 Datasets v3.0、插件系统、LIBERO/Meta-World、多 GPU |
| **ROS 2** | 机器人系统中间件 | 工程/部署岗刚需；topic / service / action、TF2、MoveIt2、Nav2 | CPU 即可 | 发行版见 L1 |
| **OpenVLA** | 开源 VLA 基线（7B） | 读代码理解「动作 token 化」的最佳范本；支持 LoRA 单卡微调；LIBERO 基准 | 微调需消费级 GPU；全量训练需 64×A100 级 | 代码 + 权重开源 |
| **Isaac Lab** | GPU 并行 RL / IL / 后训练框架 | 人形 / 四足 Sim2Real 工业标准；30+ 环境开箱即用 | **必须 RTX GPU**， heaviest 选项 | BSD-3；需与 Isaac Sim 版本配对 |
| **MuJoCo** | 高精度接触物理引擎 | 接触丰富操作、RL 基准；配合 MuJoCo Playground 的 Colab 教程最易起步 | CPU 可跑 | Apache 2.0（DeepMind） |
| **Gymnasium** | RL 环境 API 标准 | 所有 RL 代码的「通用插座」；`reset/step` 五元组；有 Gym 迁移指南 | 无 | Farama Foundation（✅ 已验证） |
| **Stable-Baselines3** | PyTorch RL 算法库 | PPO/SAC/A2C/TD3/DQN 一行调用，画奖励曲线，适合打基础 | 无 | 兼容 Gymnasium |
| **Diffusion Policy** | 扩散模型生成动作序列 | 理解「生成式策略」的核心复现项目；50–150 条演示即可出效果 | 单 GPU | Columbia / TRI |
| **ACT / ALOHA** | 动作分块 Transformer + 低成本双臂 | 中文社区公认「最经典入门项目」；理解 CVAE + action chunk | 有 ALOHA 硬件最佳，也可先在仿真复现 | `github.com/tonyzhaozh/act` |
| **RoboMimic** | 离线 IL / 离线 RL 研究框架 | 多算法、多机器人数据集、标准化评测，适合做对照实验 | 无 | `robomimic.github.io` |
| **其他值得放进收藏夹** | Octo (`github.com/octo-models/octo`)、openpi (`github.com/Physical-Intelligence/openpi`)、Isaac-GR00T (`github.com/Nvidia/Isaac-GR00T`)、LIBERO (`github.com/Lifelong-Robot-Learning/LIBERO`)、Habitat-Lab/Sim (`github.com/facebookresearch/habitat-lab`)、Gymnasium-Robotics、MuJoCo Playground、RLDS、UMI、unitree_lerobot、VLA/世界模型 14 篇阅读路线 (`github.com/ImChong/Robotics_Notebooks`) | 按方向取用 | — | — |

### 4.1 重点：LeRobot SO-100 / SO-101 硬件成本（`【易变】` 全部标注来源与时间）

- **【事实·2024-10】** SO-100：Hugging Face × The Robot Studio 发布，全 3D 打印 leader/follower 双臂，约 **100–115 美元**零件成本；6 自由度，Feetech STS3215 总线舵机，需手动拆舵机齿轮（组装 1 小时+）。Koch v1.1 是 LeRobot 2024-07 首个支持的硬件（Dynamixel 舵机）。
- **【事实·2025-04-28】** SO-101 发布（合作方增加 WowRobo、Seeed Studio、Partabot），改进布线、取消拆齿轮、优化主动臂减速比，组装约 **20 分钟**；SO-100 在官方文档中已标记为 deprecated。
  - HF CEO Clément Delangue 原话：**「It costs from $100 to $500 depending on how much you want it assembled and your country of shipping.」**
  - 官方 DIY 零件成本：**单臂 121.94 美元 / leader+follower 一对 229.88 美元**；基础价 100 美元，含 3D 打印件 + 电机套件约 130 美元；Seeed Studio 套件 **240 美元**；欧盟 **114 欧元**；**中国因关税可能接近 500 美元**。
  - 来源：https://thedynamics.ai/articles/so-101 ｜ https://ithome.com.tw/news/168646 ｜ https://gigazine.net/gsc_news/en/20250501-hugging-face-robotic-arm ｜ 今日头条《Hugging Face 推出低成本可编程 3D 打印机械臂》2025-05-01
- **【事实·配套】** 完整遥操作需要 **两条臂 + 2 个摄像头**（1 个腕部 + 1 个外部视角，720p USB 摄像头即可）；社区反馈两个**同型号**摄像头会导致 USB 路径混淆、录制脚本崩溃。
- **【事实·算力参考】** Hugging Face 博客案例（Sherry Chen，2025-09）：**52M 参数的 ACT 模型，在 12GB 显存 RTX 3080 上约 4 小时训完**。这是「消费级硬件可行」的具体锚点。
- **【易变·生态扩展】** Pollen Robotics 于 2025-04 被 HF 收购；Reachy 2 约 70,000 美元，HopeJR 全尺寸人形目标价约 3,000 美元，Reachy Mini 低于 300 美元，LeKiwi 移动底盘 2025-02 发布。以上为 2025 年报道价格，务必复核。
- **【建议】** 若预算有限，优先「单臂 + 仿真」起步；真机最大的隐藏成本不是臂本身，而是**摄像头、电源、夹具、3D 打印耗材与调试时间**。

---

## 5. 分阶段学习路线（0–3 / 3–6 / 6–12 个月）

> 参照 DataWhale（基础 1–2 月 / 定向 2–3 月 / 项目持续）、CSDN 零基础 7 阶段路线、《具身智能回理性期》五步走，以及多份 2026 年 JD 的加分项综合而成。**【建议】以下为建议，不是标准答案。**

### 阶段一：0–3 个月 —— 「跑通一条最小闭环」

| 项 | 内容 |
|---|---|
| **目标** | 建立全局认知；配好环境；在**纯仿真 + 公开数据集**上跑通「数据 → 训练 → 评估」 |
| **学** | L0 数学与 Python / Linux / Git / PyTorch；L1 坐标变换与正逆运动学概念 + ROS2 基础；L2 CNN/Transformer 概念；读 `Robot Learning: A Tutorial` 前几章 |
| **做（项目）** | ① Hugging Face Robotics Course 全程（免硬件）；② LeRobot **Push-T** 任务：下载 `lerobot/pusht` 200 段演示 → Diffusion Policy 训练 → `eval_policy` 可视化；③ Gymnasium + SB3 训练 PPO/SAC 并画奖励曲线；④ 用 `huggingface.co/spaces/lerobot/visualize_dataset` 浏览 3 个社区数据集 |
| **验收标准** | 能解释「观测 / 状态 / 动作 / action chunk」；能独立复现一次训练并复述超参作用；能说清 ROS2 的 topic / service / action 区别；产出 1 个可展示的 Git 仓库 + README |
| **避坑** | 不要在这个阶段买硬件、不要追新论文、不要同时开三个方向 |

### 阶段二：3–6 个月 —— 「按岗位定向 + 复现经典策略」

| 项 | 内容 |
|---|---|
| **目标** | 选定一条赛道（VLA 算法 / 工程落地 / 数据 / 控制），完成 2–3 个有含金量的复现 |
| **学** | L3 全量（PPO/SAC/BC/DAgger/离线 RL）；ACT / Diffusion Policy / OpenVLA 架构；L1 进阶（UR5 逆解、轨迹规划、阻抗控制、手眼标定、点云）；L5 一种仿真器深入（MuJoCo 或 Isaac Sim） |
| **做（项目）** | ① **ACT 经典复现**（跑通训练→测试→推理，DataWhale 列为第一项目）；② **ROS2 机械臂控制仿真**（正逆解 + 抓取闭环 + 接入 Gazebo / Isaac Sim）；③ **开源数据集处理**（OXE 或 LIBERO：读懂→清洗→转换→可视化→生成可训练格式，门槛低、易出结果）；④ **Diffusion Policy 复现与微调**；⑤ 有余力做 OpenVLA-OFT 在 LIBERO 上的微调 |
| **验收标准** | 能在同一任务上对比 BC / ACT / Diffusion Policy 的成功率并解释差异；能读懂奖励曲线并定位失败原因；能把一个策略部署到仿真机械臂上连续跑 20 次并统计成功率；开始写技术博客 / 复现笔记 |
| **对应 JD 加分项** | 「复现过 OpenVLA、RDT」「有 ACT、扩散策略、VLA、真机 RL 相关研究或工程经验」 |

### 阶段三：6–12 个月 —— 「打通 Sim2Real 与作品集」

| 项 | 内容 |
|---|---|
| **目标** | 形成「数据 → 训练 → 部署 → 真机/准真机验证」的完整作品集，对准顶会 / 开源贡献 / 求职 |
| **学** | L4 全部（VLA 家族、世界模型、OXE/DROID/LeRobot 数据管线）；L5 域随机化、系统辨识、推理加速（量化 / TensorRT / 异步推理）、多模态融合（视觉+力觉+触觉）、动作 chunk 与高低频双系统 |
| **做（项目）** | ① **OpenVLA / SmolVLA 微调与部署**（数据准备→微调→推理测试→部署，最接近一线工作流）；② **Isaac Sim Sim2Real**：搭场景 → 域随机化训练 → 记录 sim/real 成功率差；③ 用 SO-101 采集 50 条演示训 ACT，记录首次成功率，再补 50 条覆盖失败案例、重训并对比（这个「前后成功率数字」本身就是最好的作品集素材）；④ 争取一个开源 PR（LeRobot 插件 / 文档 / bugfix）或一篇 workshop 论文 |
| **验收标准** | 有一个端到端项目能从遥操作采集跑到真机自主执行，并给出**带基线对比、失败分析、随机种子/版本记录**的报告；能解释 sim2real gap 的三类来源（视觉 / 动力学 / 传感器噪声）与对应缓解手段 |
| **面试信号** | 「能讲清楚自己关注的论文和原因」（中科大 JD 原文） |

### 5.1 三种硬件条件下的替代路径（`【建议】`）

| 条件 | 路径 | 可达成目标 | 明确做不到的事 |
|---|---|---|---|
| **零硬件** | HF Robotics Course → LeRobot Push-T / LIBERO / Meta-World 仿真 → 社区数据集可视化与清洗 → Gymnasium+SB3 → 读 OpenVLA/π0 代码 → 在 Colab 上 LoRA 微调 SmolVLA/OpenVLA | 完整掌握数据管线、训练、评测、模型结构；足以投递「数据 / 仿真 / 算法（初级）」岗位 | 真机接触、力控、标定、延迟、传感器噪声等物理经验；简历上需诚实标注「仿真」 |
| **消费级硬件**（一台带 RTX 显卡的 PC，无机械臂） | 在零硬件基础上加：Isaac Sim/Isaac Lab 或 MuJoCo 本地仿真、本地微调 7B 以下模型、Blender/Replicator 合成数据、域随机化实验；可参加 RoboCup 仿真赛 / 智源具身大模型挑战赛等提供算力的赛事 | 可做 RL 大规模并行训练、VLA 微调、Sim2Real 前半段；**性价比最高的自学期配置** | 最后的 real 环节 |
| **有真机**（SO-101 级 / ALOHA 级 / 实验室 Franka、Unitree G1） | 完整四步闭环；重点做数据采集质量、标定、力/触觉融合、真机 RL（HIL-SERL）、推理延迟优化、系统辨识；把「补数据 → 成功率提升」做成可量化实验 | 对齐「真机部署 / 落地经验」这一最稀缺能力 | — |

> **【建议】** 三条路径不是互斥的，推荐顺序是：**先零硬件跑通 → 加 GPU 做规模 → 最后上真机补物理直觉**。反过来（先买臂再学代码）是本轮中文社区复盘中最常见的浪费。

---

## 6. 新手常见坑与建议

### 坑 1 · 只刷论文不碰真机 / 只跑仿真
- **【事实】** 多份 2026 JD 明确写「愿意深入真实机器人进行算法验证和迭代，**不局限于离线模型指标**」「有 Manipulation 或真机学习项目经验」加分；《具身智能回理性期》直言「企业看重的是你解决过什么问题、能不能把系统跑起来，而不是你读了多少论文」。
- **【建议】** 每读一篇论文，强制配一个最小复现；把「成功率 + 失败案例截图」写进笔记，而不是只记架构图。

### 坑 2 · 低估 Sim2Real gap
- **【事实】** gap 有三类来源：**视觉 gap**（纹理/光照/反射/运动模糊）、**动力学 gap**（简化接触模型，摩擦/柔顺/形变）、**传感器噪声 gap**（深度相机结构化噪声、丢帧、50–200 ms 延迟）。行业经验：视觉参数可激进随机化，物理参数须围绕实测值保守随机化；即便激进域随机化，真机成功率仍常见 **15–30%** 下滑；接触密集任务（精密插装、柔性物体）迁移最差。最有效的是三段式：仿真域随机化预训练 → 在部署硬件上采 targeted 真机数据 → 用真机数据微调（约 **10:1 的 sim:real 比例**，比从零训练省 3–5× 真机数据）。
- **【事实·经典文献】** Tobin et al., IROS 2017（Domain Randomization）；Peng et al., ICRA 2018（Dynamics Randomization）；Akkaya et al., 2019（Solving Rubik's Cube with a Robot Hand）；Zhao et al., 2020 综述 arXiv:2009.13303。
- **【建议】** 域随机化不是银弹；**不要把「仿真成功率」当验收指标**，把「真机 N 次试验成功率 / sim2real gap 百分比 / 无干预连续成功次数」写进 KPI。

### 坑 3 · 数据稀缺 + 数据质量
- **【事实】** 真机演示昂贵，动作数据远少于图文；OXE 前四类机器人占真机数据 85%+，且以桌面单臂 pick-and-place 为主；简单 BC 有**复合误差**问题。HF 博主 Sherry Chen（2025-09）记录的两个真实翻车：① 两个同型号 USB 摄像头导致路径重分配、每 5 个 episode 崩一次；② 采集时「回头偷看从动臂」，等于给模型注入了它推理时拿不到的信息，第一次训练完全没学会。
- **【建议】** 先花时间把采集 SOP 固定（摄像头型号区分、视角、演示一致性、失败案例覆盖），再谈换模型；补 50 条针对性数据往往比换架构有效。

### 坑 4 · 算力 / 版本 / 环境门槛
- **【事实】** OpenVLA 原训练用了 64×A100×15 天；GR00T N1.7 推理需 16GB+ 显存；Isaac 系需 RTX 显卡且有严格版本配对；Isaac Sim 与 ROS2 对 Ubuntu / Python 版本有固定组合。
- **【建议】** 入门避开 7B 全量训练，走 **SmolVLA（450M）/ LoRA 微调 / 消费级单卡**；把「版本锁定 + 随机种子 + 配置文件 + 依赖清单」当成第一生产力；升级前先复制一个已知场景做回归对比。

### 坑 5 · 追新、贪多、方向并行
- **【建议】** 中文零基础路线的三条共识值得抄：**仿真优先低成本入门、先跑通再深究、单点深耕不贪多**（锁定机械臂或移动机器人单一赛道）。VLA / 世界模型每周都有新论文，专题页和学习计划都要标注「资料截止日期」。

### 坑 6 · 只学 AI，不学机器人学 / 只学机械，不学 AI
- **【事实】** 人才报告把「懂算法的不懂本体、懂机械的不懂大模型」列为能力断层；有招聘方明确偏好「逆解推导清楚」的候选人。
- **【建议】** 至少补到能与对方对话的程度：算法侧要懂坐标变换/逆解/控制频率；机械侧要懂 Transformer / 数据管线 / 推理部署。

### 坑 7 · 引用不实数字
- **【建议】** 本轮已发现多处口径冲突（OXE 规模 4 种说法、珞石成立年份 2014/2015 两种说法、模拟器版本号二手来源不一致）。专题页对所有数字统一加「来源 + 时间」，论文/榜单以 arXiv、官方仓库、官方博客为准。

---

## 7. 事实与建议速查索引（方便网页做筛选标签）

| 类型 | 本报告中的典型条目 |
|---|---|
| **【事实·已 WebFetch 直连验证】** | CS285 2026 春季课程与作业清单；VLA 综述 IEEE Access 2025 / DOI / arXiv；Robot Learning: A Tutorial arXiv:2510.12403；ROS 2 发行版与支持期；OpenVLA 7B / 97 万 episodes；Spinning Up 算法清单；Gymnasium 定义；Modern Robotics 教材与 6 门 Coursera 课；RoboCup 2026 仁川；Isaac Lab 3.0.0 / BSD-3 / 兼容表；DataWhale 学习路径；HF LeRobot 仓库 |
| **【事实·招聘 / 媒体 / 二手报告】** | 六大岗位能力要求；薪资区间；招聘指数 15 倍；教育部 2026 新增具身智能专业；两项国内赛事数据；SO-101 价格；数据集规模；社区与竞赛清单 |
| **【易变·必须复核】** | 所有薪资、ROS2/Isaac/MuJoCo/Gazebo 版本号、模型参数量与发布时间、数据集规模、SO-101 价格、HF 组织页数据集/模型数量 |
| **【建议·本报告判断】** | 知识栈分层与验收标准、三阶段路线、三种硬件条件替代路径、7 个坑的应对、公司四分法、先仿真后真机的顺序 |

---

## 附录：主要来源清单（标题 + URL）

### A. 招聘与行业现状
1. 具身算法工程师（珞石机器人，燕山大学就业平台，2026-08）— https://job.ysu.edu.cn/jyxt/sczp/zpztgl/ckZpgwXq.zf?zpxxbh=59E90E80B708F90EE0630100007F8978
2. 具身智能算法工程师（珞石 ROKAE，猎聘，2026-10）— https://www.liepin.com/job/1985176799.shtml
3. 具身智能算法工程师（纽鼐机器人，中科大就业网，2026-10-09）— https://job.ustc.edu.cn/Jobinformation/list.aspx?itemid=329302
4. 具身智能(VLA)技术专家（意界智创 Enacta AI，猎聘，2026-10）— https://m.liepin.com/job/1985379447.shtml
5. 算法工程师（智联招聘，含 VLA/ACT/Diffusion Policy 与四个岗位方向）— https://www.zhaopin.com/jobdetail/CCL1478801640J40879440801.htm
6. 机器人行业招聘｜一批具身智能核心岗位正在开放（CSDN DAMO）— https://damodev.csdn.net/6a8fff91662f9a54cba1392b.html
7. 年薪百万招 0 工作经验工程师，具身智能「卷」起来了（腾讯新闻，2026-03-19）— https://news.qq.com/rain/a/20260319A07IW000
8. 2026 具身智能人才报告：招聘指数 15 倍（三个皮匠报告 / 华博咨询）— https://bg.sgpjbg.com/labels/2026zhongguojushenzhinengjiqirenxingyerencaifazhanbaogao/1/7748021.html
9. 具身智能抢人大战：核心岗位与薪资全拆解（今日头条，2026）— https://www.toutiao.com/a7677464604275950118
10. 人形机器人招聘与具身智能人才：智元优才计划最缺哪类人（亨德森猎头）— https://www.hendersonexecutive.com/news/219.html

### B. 课程、教材、教程与综述（学术 / 官方）
11. CS 285 Deep Reinforcement Learning（UC Berkeley）— https://rail.eecs.berkeley.edu/deeprlcourse/
12. OpenAI Spinning Up in Deep RL — https://spinningup.openai.com/en/latest/
13. Modern Robotics（Lynch & Park，免费 PDF + Coursera/edX 课程）— http://lynchandpark.org/
14. Reinforcement Learning: An Introduction 2nd ed.（Sutton & Barto 免费版）— http://incompleteideas.net/book/the-book-2nd.html
15. Robot Learning: A Tutorial（arXiv:2510.12403，2025-10-14）— https://arxiv.org/abs/2510.12403
16. VLA Survey（IEEE Access 2025）— https://vla-survey.github.io/ ｜ https://arxiv.org/abs/2510.07077 ｜ https://ieeexplore.ieee.org/document/11164279
17. A Survey: Learning Embodied Intelligence from Physical Simulators and World Models（arXiv:2507.00917v3）— https://arxiv.org/abs/2507.00917v3 ｜ https://github.com/NJU3DV-LoongGroup/Embodied-World-Models-Survey
18. A Comprehensive Survey on World Models for Embodied AI（2025-10-19）— https://arxiv.org/html/2510.16732v1 ｜ 中文解读 https://www.thepaper.cn/newsDetail_forward_33663759
19. OpenVLA 项目页 / 论文 — https://openvla.github.io/ ｜ https://arxiv.org/abs/2406.09246
20. OpenVLA-OFT — http://openvla-oft.github.io/
21. Diffusion Policy 论文 — https://arxiv.org/abs/2303.04137
22. Sim-to-Real Transfer in Deep RL for Robotics: A Survey — https://arxiv.org/abs/2009.13303
23. Hugging Face Robotics Course（免硬件）— https://huggingface.co/learn/robotics-course/unit0/1
24. DataWhale Dive into Embodied AI 学习路径 — https://datawhalechina.github.io/dive-into-embodied-ai/docs/overview/learning-path ｜ https://github.com/datawhalechina/dive-into-embodied-ai
25. DataWhale 官网（含《从零开始学具身智能 Every-Embodied》）— https://www.datawhale.cn/
26. Xbotics 具身智能手册（19 讲 + 全部开源链接）— https://github.com/Xbotics-Embodied-AI-club/Xbotics-Embodied-AI-Handbook
27. VLA 与世界模型：14 篇论文阅读路线 — https://github.com/ImChong/Robotics_Notebooks
28. 李宏毅课程主页 — https://speech.ee.ntu.edu.tw/hylee/index.php

### C. 官方文档与开源仓库
29. ROS 2 官方文档 — https://docs.ros.org/ ｜ 新手教程 https://docs.ros.org/en/lyrical/Tutorials.html ｜ 包索引 https://index.ros.org/ ｜ Discourse https://discourse.ros.org/
30. Gazebo — https://gazebosim.org/docs/latest/getstarted/
31. Gymnasium（Farama Foundation）— https://gymnasium.farama.org/
32. LeRobot 仓库 / 文档 / 组织页 — https://github.com/huggingface/lerobot ｜ https://huggingface.co/docs/lerobot/index ｜ https://huggingface.co/docs/lerobot/so101 ｜ https://huggingface.co/lerobot
33. Isaac Lab 仓库 / 文档 — https://github.com/isaac-sim/IsaacLab ｜ https://isaac-sim.github.io/IsaacLab/main/
34. Stable-Baselines3 — https://github.com/DLR-RM/stable-baselines3 ｜ https://stable-baselines3.readthedocs.io/
35. RoboMimic — https://github.com/ARISE-Initiative/robomimic ｜ https://robomimic.github.io/
36. ACT / ALOHA — https://github.com/tonyzhaozh/act ｜ https://github.com/tonyzhaozh/aloha
37. Diffusion Policy — https://github.com/real-stanford/diffusion_policy
38. Octo / openpi / GR00T / LIBERO / Habitat — https://github.com/octo-models/octo ｜ https://github.com/Physical-Intelligence/openpi ｜ https://github.com/Nvidia/Isaac-GR00T ｜ https://github.com/Lifelong-Robot-Learning/LIBERO ｜ https://github.com/facebookresearch/habitat-lab
39. Open X-Embodiment — https://github.com/google-deepmind/open_x_embodiment ｜ https://robotics-transformer-x.github.io/
40. RLlib（Ray）— https://github.com/ray-project/ray ｜ https://docs.ray.io/en/latest/rllib/index.html
41. SmolVLA 模型 — https://huggingface.co/lerobot/smolvla_base
42. NVIDIA Isaac GR00T 官方页 — https://developer.nvidia.com/isaac/groot

### D. 硬件成本（2025 年报道，价格易变）
43. SO-101 深度解析（含 $121.94 / $229.88 成本明细与时间线）— https://thedynamics.ai/articles/so-101
44. The History of LeRobot（版本史、SmolVLA、Datasets v3.0）— https://thedynamics.ai/articles/lerobot
45. Hugging Face 公布 3D 列印機器手臂 DIY 成本不到 500 美元（iThome，2025-04）— https://ithome.com.tw/news/168646
46. Hugging Face unveils SO-101（GIGAZINE，2025-05-01，含 Seeed Studio $240）— https://gigazine.net/gsc_news/en/20250501-hugging-face-robotic-arm
47. Hugging Face 推出低成本可编程 3D 打印机械臂（今日头条，2025-05-01）— https://www.toutiao.com/article/7499315372881920552
48. LeRobot v0.4.0 正式发布（HF 官方博客中文转载，CSDN）— https://blog.csdn.net/huggingface/article/details/154104562
49. Best Robot Learning Datasets 2025 / 开源生态 2025（Silicon Valley Robotics Center）— https://www.roboticscenter.ai/research/best-robot-learning-datasets-2025 ｜ https://www.roboticscenter.ai/research/open-source-robot-learning-ecosystem
50. Open X-Embodiment Dataset Explained（含规模口径与许可说明）— https://roboticaguide.com/open-x-embodiment-dataset-explained

### E. 学习路线、社区与坑
51. 基础差/零基础人员具身智能学习路线（CSDN DAMO，7 阶段）— https://damodev.csdn.net/6a50abe810ee7a33f28c3e32.html
52. 2025 具身智能入门指南：从小白到实战（CSDN）— https://myhqh.blog.csdn.net/article/details/156942699
53. 具身智能回理性期：从技术栈拆解到学习路线与面试指南 — http://www.hqwc.cn/a/1909338.html
54. 一文详细梳理具身智能操作类学习路线（模仿学习与强化学习，腾讯新闻转载，含 CS285 / Spinning Up / SB3 / RoboMimic）— https://news.qq.com/rain/a/LNK2025061203510300
55. 2024-2025 年 VLA 模型前沿研究报告（CSDN DAMO）— https://damodev.csdn.net/6a79f03c10ee7a33f2992b75.html
56. VLA 模型：概念、演进、代表工作与挑战（CSDN DAMO）— https://damodev.csdn.net/6ac75b8705257b0857155cd9.html
57. VLA 学习路线（科技区角）— https://www.x-techcon.com/article/6131.html
58. 告别万元硬件与复杂算法：Hugging Face LeRobot 带你零门槛闯入具身智能（EmboX 具身工坊，含 Push-T 实战代码）— http://mp.weixin.qq.com/s?__biz=Mzg2Mzg2NDM0OA==&mid=2247484610&idx=1&sn=5f9f82c54caf76c110538848a99402cf
59. 手把手带你入门机器人学习：HuggingFace 联合牛津大学新教程开源（机器之心）— http://mp.weixin.qq.com/s?__biz=MzA3MzI4MjgzMw==&mid=2650997862&idx=2&sn=d680e676f695732125af20853bcc799c
60. 领域随机化：2025 年的全面指南 — https://www.shadecoder.com/zh/topics/domain-randomization-a-comprehensive-guide-for-2025
61. Sim-to-Real Gap：Why Simulated Robot Policies Fail on Real Hardware — https://claru.ai/glossary/sim-to-real-gap
62. Sim-to-Real Transfer for Manipulation: What Works in 2025 — https://www.roboticscenter.ai/hi/research/sim-to-real-transfer-manipulation-2025
63. 机器人仿真器比较：Isaac Sim、MuJoCo 与 Gazebo（2026-10 版本核对，二手，需复核）— https://physicalailab.io/zh/robot-simulator-comparison-guide-zh/

### F. 竞赛
64. 2025 中国机器人大赛暨 RoboCup 机器人世界杯中国赛落幕（科技日报，2025-10-20）— https://www.stdaily.com/web/gdxw/2025-10/20/content_418037.html
65. 同上（中国日报网）— https://cn.chinadaily.com.cn/a/202510/20/WS68f59b92a310c4deea5ed1c4.html
66. 人形机器人「巅峰对决」在合肥（中新网安徽，2025-08-24）— https://www.ah.chinanews.com.cn/news/2025/0824/336494.shtml
67. RoboCup 官方网站（RoboCup 2026 仁川）— https://www.robocup.org/

---

### 链接验证说明（供内容上线前复核）

- **WebFetch 直连验证通过**：`rail.eecs.berkeley.edu/deeprlcourse`、`spinningup.openai.com`、`vla-survey.github.io`、`arxiv.org/abs/2510.12403`、`docs.ros.org`、`lynchandpark.org`、`openvla.github.io`、`datawhalechina.github.io/dive-into-embodied-ai`、`gymnasium.farama.org`、`robocup.org`、`github.com/huggingface/lerobot`、`github.com/isaac-sim/IsaacLab`。
- **搜索引擎索引 + 多来源交叉确认**（HF 域名在本环境 WebFetch 直连受限，但页面内容由搜索结果与多个独立引用一致确认）：`huggingface.co/learn/robotics-course/unit0/1`、`huggingface.co/docs/lerobot/index`、`huggingface.co/docs/lerobot/so101`、`huggingface.co/lerobot`。
- **仅据检索结果列出、未直连验证**的 GitHub 仓库与社区链接，已在正文标注来源；建议网页上线前用批量 HTTP 状态检查过一遍。
- **未验证到稳定 URL 因此未给出链接**：智源社区具身智能小组、古月居、知乎相关专栏、ROSChina 主站——正文仅以名称提及，避免编造 URL。
- **未编造任何论文条目**：所有 arXiv 编号、DOI、模型参数、价格均来自上述检索结果或 WebFetch 页面；互相冲突处已在正文显式标注口径差异。
