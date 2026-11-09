# 具身智能学习硬件价格表 — 检索与验证记录

- 日期：2026-11-05
- 输出：`lrc-hardware-prices.json`（26 条）+ 本文
- 原则：**绝不编造价格**。凡查不到官方/可靠报价的字段一律 `null`，并在 `note` 写明原因、币种、时点与口径。人民币优先；美元按 1 USD ≈ 7.1 CNY 仅作量级参考，不做无依据的换算填入 `priceCny`。
- 工具：WebSearch（多轮）+ WebFetch（正文复核）+ `curl -L -o /dev/null -w "%{http_code}"`（HTTP 实测）。

---

## 一、检索轮次与过程

**第 1 轮｜官方套件与整机基准价**
- `Seeed Studio SO-100 SO-101 LeRobot arm kit price USD official store` → 命中 Seeed 官方商品页：SO-ARM101 Pro 已组装单臂 **$299.00**（SKU 100046482）、仅舵机套件 **$249.90**（SKU 114993667）、3D 打印件 **$29.90**；官方 PDF 标 `Excl. VAT`。
- `WowRobo SO-100 SO-101 LeRobot kit price` → 命中 thedynamics.ai / pcnmobile / 硅基部落，得到 WowRobo $199–$299、OpenELAB 渠道 $325.99/$419.99/$489.99，以及 GitHub 官方 BOM 单臂 $121.94 / 双臂 $229.88、中国区 ¥682 / ¥1,343。
- `Unitree G1 R1 humanoid robot price USD official` → 官方商城 G1 $13,500 / R1 $4,900 / R1-A $4,290 / Go2 $1,600；宇树官网首页另写 "Price from $16K"，出现第一处口径冲突。
- `NVIDIA Jetson Orin Nano Super Developer Kit price $249 official` → NVIDIA 官方页与官方博客确认 **$249**（原价 $499）。

**第 2 轮｜开发板、传感器、国内云算力**
- `Jetson Orin NX 16GB module price` → Seeed Robotics J4012 **$1,657.99**、Industrial J4012 **$1,749**、标准 J4012 约 **$1,399**；天猫出现 ¥493 的"16GB"低价，实为底板/最低配变体引流价。
- `Raspberry Pi 5 8GB price official` → 官方涨价公告给出 $45/$55/$70/$95/$145；但 raspberry.tips 追踪到 2026-10 挂牌 $77.50/$110/$175/$305，出现明显冲突。
- `Intel RealSense D435 D405 price official store` → 搜索缓存显示 D435 $314、D405 $272；**2026-11-05 用 WebFetch 直取官方商店，实价已为 D435 $375、D405 $325**（官网近期提价），这是本轮最重要的校正。
- `AutoDL 云 GPU 4090 按时计费` → 官网首页 ¥1.88/时(4090)、¥1.32/时(3090)、¥2.78/时(5090)，会员 95 折；媒体报价从 ¥1.58 到 ¥3.98/时不等。

**第 3 轮｜消费卡、海外云算力、零成本仿真**
- `RTX 5090 4090 3090 显卡 京东 价格` → diy52.com 京东自营快照（2026-05）：3090 ¥6,699、4090 ¥21,799、4090 D ¥17,499、5090 ¥34,999；京东商品页另有 4090 涡轮工包 ¥31,200、淘宝 5090 引流价 ¥55,599。
- `RunPod / Lambda pricing` → RunPod 官方定价页 4090 $0.69/hr、3090 $0.46/hr、5090 $0.99/hr；Lambda 官方 `/pricing` 记 A100 40GB $1.99/GPU/hr，而 `/service/gpu-cloud` 同配置记 $1.29/hr（官方两页口径不一致）。
- `Colab Pro / Kaggle free GPU quota` → Kaggle 官方页确认 30 h/周；Colab 官方域名在本环境被拦截（curl 000），改用 2026 年媒体评测作为可访问来源并记录限制。
- `MuJoCo free / Isaac Sim free` → MuJoCo 官网 Apache 2.0 免费；Isaac Sim 软件免费但受 Omniverse 许可约束。

**第 4 轮｜双臂、UMI、力传感器、整机人民币价**
- `Mobile ALOHA cost BOM` → Trossen 官方 FAQ 约 $20,000；ICLR 2026 LeRobot 论文 Table 1a 记 ALOHA ~€21k、Koch ~€670/€1,346、LeKiwi ~€230、HopeJR ~€500；第三方拆解 Mobile ALOHA $28,000–35,000。
- `UMI gripper cost BOM` → arXiv 论文原文：打印夹爪 BOM $73 + GoPro 及配件 $298 ≈ $371；UMI-3D GitHub BOM 目标 ≈¥5,000（含 Livox MID-360 ¥3,599–3,999）。
- `六维力传感器价格` → 传感器专家网记 2026-05 奥松 MEMS 统一 ¥1,999；产业口径国产 ¥5,000–8,000、进口 ATI 2–8 万；百度 B2B 存在 ¥2/台 的询价占位价。
- `宇树 R1 人民币官方售价` → **重大发现**：unitree.com/R1 官方页明码"售价(含税) R1 AIR ¥2.99万 / R1 ¥3.99万 / R1 EDU 联系销售"；同时 unitree.com/g1 规格表显示 G1 基础版 `Secondary Development: /`、G1 EDU 才 `YES`。
- `Unitree Go2 人民币` → 百度百科记起售 ¥9,997；京东自营 Go2 Air ¥14,699 / Pro ¥18,989 / **Go2 EDU 可开发版 ¥89,999**。

**第 5 轮｜补齐官方 URL 与隐性成本**
- 找到 Seeed 官方直链：X10 USB 摄像头 **$12**、Feetech ST3215-C047 舵机 **$22**、SO-101 3D 打印件 **$29.90**；Raspberry Pi 官方 27W 电源 $12 / 45W $15。
- `WowRobo site:openelab.io` → OpenELAB 官方经销页（WebFetch 实取：基础档 €409.45 含 VAT / €344.08 未税，且页面明确警告"基础档不是完整 leader–follower 系统"）。
- `Lambda 官方 pricing`、`Kaggle 官方 GPU tips` → 拿到可实测的官方 URL。

---

## 二、URL 实测验证

方法：对 JSON 中每条 `url` 用 `curl -sS -L -o /dev/null -w "%{http_code}" --max-time 18 -A "<浏览器 UA>"` 跟随跳转取最终状态码；对关键价格页再用 WebFetch 抓取正文复核数字。

- JSON 共 **26 条**，去重后 **23 个唯一 URL**。
- 首轮实测：**23 个唯一 URL 全部返回 HTTP 200**。
- 末轮复核：22 个仍为 200；`https://openelab.io/de/products/wowrobo-robotics-so-arm101-diy` 因 Shopify 对本次 IP 限流返回 **429**（首轮为 200，且本会话 WebFetch 已成功抓取完整商品正文与价格，链接真实可访问，非 404/不可达）。
- 被放弃的候选链接（不进入 JSON）：`colab.research.google.com` 等 Google 域名 000（本环境网络拦截）、`baike.baidu.com` 403、`3dconnexion.com` 官方商品页 403、`3dxworld.com` 429、`thedynamics.ai` / `robonomy.net` 000、`openelab.com` 429、`www.seeedstudio.com/Feetech-ST3215...-p-6340.html` 404（改用 media-cdn.seeedstudio.com 的 200 页面）。这些仅在 `note` 中作为参考来源被提及，并注明未通过实测。

**23 个唯一链接清单（均为 200 首轮实测）**

| # | URL | 用途 |
|---|---|---|
| 1 | https://aisotools.com/blog/google-colab-review-2026 | Colab 免费层 |
| 2 | https://www.kaggle.com/page/GPU-tips-and-tricks | Kaggle 30h/周 |
| 3 | https://mujoco.org/ | MuJoCo 免费 |
| 4 | https://developer.nvidia.com/isaac/sim | Isaac Sim 免费 |
| 5 | https://www.seeedstudio.com/SO-101-Assembled-Kit-Pro-p-6691.html | SO-101 组装臂 $299 |
| 6 | https://openelab.io/de/products/wowrobo-robotics-so-arm101-diy | WowRobo 套件（首轮 200，复核 429） |
| 7 | https://www.trossenrobotics.com/post/aloha-robot-low-cost-bimanual-platform | ALOHA ~$20k |
| 8 | https://proceedings.iclr.cc/paper_files/paper/2026/file/c702175bc31584c52c28cc20731db371-Paper-Conference.pdf | LeRobot 论文成本表 |
| 9 | https://www.nvidia.com/zh-tw/autonomous-machines/embedded-systems/jetson-orin/nano-super-developer-kit/ | Jetson $249 |
| 10 | https://www.seeedstudio.com/reComputer-Robotics-J4012-p-6505.html | Orin NX 16GB |
| 11 | https://www.raspberrypi.com/news/1gb-raspberry-pi-5-now-available-at-45-and-memory-driven-price-rises/ | Pi 5 官方价 |
| 12 | https://www.diy52.com/vga/index_13.html | 3090/4090/5090 京东快照（3 条共用） |
| 13 | https://www.autodl.com/home | AutoDL 时租 |
| 14 | https://www.runpod.io/pricing | RunPod 时租 |
| 15 | https://store.realsenseai.com/ | D435 / D405 官方实价（2 条共用） |
| 16 | https://www.seeedstudio.com/X10-USB-wired-camera-p-6506.html | USB 摄像头 $12 |
| 17 | https://m.sensorexpert.com.cn/article/490174.html | 六维力 ¥1,999 |
| 18 | https://www.nosco.com.sg/?p=250/ | SpaceMouse $149 |
| 19 | https://www.unitree.com/R1/ | R1 含税人民币价 |
| 20 | https://shop.unitree.com/ | G1/R1/Go2 美元价 |
| 21 | https://arxiv.org/html/2402.10329v3 | UMI 论文 BOM |
| 22 | https://media-cdn.seeedstudio.com/STS3215-30KG-Serial-Servo-p-6340.html | 舵机 $22 |
| 23 | https://www.seeedstudio.com/SO-101-3D-printed-Enclosure-p-6428.html | 3D 打印件 $29.90 |

补充实测 200、写入 `note` 的参考链接：`https://www.unitree.com/g1/`（G1 规格表）、`https://www.unitree.com/`、`https://www.raspberrypi.com/news/raspberry-pi-45w-usb-c-power-supply-on-sale-now-at-15/`、`https://www.lambda.ai/pricing`、`https://developer.aliyun.com/article/1774947`、`https://www.realsenseai.com/cn/compare-all-cameras`、`https://pcnmobile.com/hugging-faces-100-3d-printed-robot-arm-explained-what-the-so-101-really-costs`、`https://www.aiddithome.com/p/dd6476133d841.html`、`https://physicalailab.io/en/so-101-robot-arm-kit-cost-buy-setup`、`https://www.edgechat.ai/lerobot`、`https://sekin.in/best-3d-mice-for-autodesk-fusion-360-design-and-modeling`。

---

## 三、逐条价格来源清单

| id | 名称 | 主要价格 | 来源 | url |
|---|---|---|---|---|
| colab-free | Colab 免费版 | ¥0 / $0 | AISO Tools 2026 评测 | [链接](https://aisotools.com/blog/google-colab-review-2026) |
| kaggle-free-gpu | Kaggle 免费 GPU | ¥0 / $0，30h/周 | Kaggle 官方 | [链接](https://www.kaggle.com/page/GPU-tips-and-tricks) |
| mujoco-sim | MuJoCo | ¥0 / $0 | 官网 Apache 2.0 | [链接](https://mujoco.org/) |
| isaac-sim | Isaac Sim | ¥0 / $0 | NVIDIA 官网 | [链接](https://developer.nvidia.com/isaac/sim) |
| seeed-so101-assembled | Seeed SO-101 组装臂 | $299（未税） | Seeed 官方商店 | [链接](https://www.seeedstudio.com/SO-101-Assembled-Kit-Pro-p-6691.html) |
| wowrobo-so101 | WowRobo 套件 | $199–$489.99 / €344.08–409.45 | OpenELAB 官方经销 + 媒体 | [链接](https://openelab.io/de/products/wowrobo-robotics-so-arm101-diy) |
| aloha-mobile-aloha | ALOHA / Mobile ALOHA | $20,000–$35,000 | Trossen 官方 FAQ | [链接](https://www.trossenrobotics.com/post/aloha-robot-low-cost-bimanual-platform) |
| koch-lekiwi-openarm | Koch / LeKiwi / HopeJR | €230–€1,346 | LeRobot ICLR 2026 论文 | [链接](https://proceedings.iclr.cc/paper_files/paper/2026/file/c702175bc31584c52c28cc20731db371-Paper-Conference.pdf) |
| jetson-orin-nano-super | Jetson Orin Nano Super | $249 | NVIDIA 官方 | [链接](https://www.nvidia.com/zh-tw/autonomous-machines/embedded-systems/jetson-orin/nano-super-developer-kit/) |
| jetson-orin-nx-16gb | Orin NX 16GB 整机 | $1,399–$1,749 | Seeed 官方商店 | [链接](https://www.seeedstudio.com/reComputer-Robotics-J4012-p-6505.html) |
| raspberry-pi-5 | 树莓派 5 | $45–$145 | Raspberry Pi 官方公告 | [链接](https://www.raspberrypi.com/news/1gb-raspberry-pi-5-now-available-at-45-and-memory-driven-price-rises/) |
| rtx-3090-cn | RTX 3090 国内 | ¥6,699 | diy52 京东快照 2026-05 | [链接](https://www.diy52.com/vga/index_13.html) |
| rtx-4090-cn | RTX 4090 国内 | ¥21,799 | diy52 京东快照 2026-05 | [链接](https://www.diy52.com/vga/index_13.html) |
| rtx-5090-cn | RTX 5090 国内 | ¥34,999 | diy52 京东快照 2026-05 | [链接](https://www.diy52.com/vga/index_13.html) |
| autodl-hourly | AutoDL | ¥1.88/时(4090) | AutoDL 官网实时 | [链接](https://www.autodl.com/home) |
| runpod-hourly | RunPod | $0.69/时(4090) | RunPod 官方定价页 | [链接](https://www.runpod.io/pricing) |
| realsense-d435 | RealSense D435 | $375（官网实价） | RealSense 官方商店 | [链接](https://store.realsenseai.com/) |
| realsense-d405 | RealSense D405 | $325（官网实价） | RealSense 官方商店 | [链接](https://store.realsenseai.com/) |
| usb-webcam | X10 USB 摄像头 | $12 | Seeed 官方商店 | [链接](https://www.seeedstudio.com/X10-USB-wired-camera-p-6506.html) |
| force-torque-sensor | 六维力传感器 | ¥1,999 起 | 传感器专家网 | [链接](https://m.sensorexpert.com.cn/article/490174.html) |
| teleop-spacemouse | SpaceMouse Compact | $149 | 授权经销商 NOSCO | [链接](https://www.nosco.com.sg/?p=250/) |
| unitree-g1-r1 | 宇树 G1 / R1 | ¥29,900 起 / $13,500 | 宇树官网 + 官方商城 | [链接](https://www.unitree.com/R1/) |
| unitree-go2 | 宇树 Go2 | ¥9,997 起 / $1,600 | 宇树官方商城 | [链接](https://shop.unitree.com/) |
| umi-gripper | UMI 手持夹爪 | ≈$371 | UMI 官方论文 arXiv | [链接](https://arxiv.org/html/2402.10329v3) |
| feetech-sts3215-servo | STS3215 舵机 | $22/颗 | Seeed 官方商店 | [链接](https://media-cdn.seeedstudio.com/STS3215-30KG-Serial-Servo-p-6340.html) |
| hidden-costs-kit | 打印件/电源/工作台 | $29.90 起 | Seeed + Raspberry Pi 官方 | [链接](https://www.seeedstudio.com/SO-101-3D-printed-Enclosure-p-6428.html) |

---

## 四、明显的价格口径冲突与不确定性

1. **宇树 G1：同一家官网三个价。** `unitree.com` 首页写 "Price from $16K"；`/g1/` 产品页与 `shop.unitree.com` 写 **$13,500**（且明确 `Tax and Shipping cost excluded`）；京东自营 **G1 EDU U2 ¥198,550–209,000**、带算力包版 **¥308,950**；科普中国记国内起售价 **9.9 万元**。核心差异在于基础版 vs EDU 版，见下条陷阱。
2. **基础版不支持二次开发（最危险）。** `/g1/` 规格表：`Secondary Development` 一栏 G1 = `/`、G1 EDU = `YES`；R1 官网也把 `R1 EDU` 列为"联系销售"。也就是说 $13.5K / ¥2.99万 的低价是"能动能跳"的展示机，做研究要买 EDU，价格翻数倍且不公开。Go2 同理：消费版 ¥14,699–18,989，**Go2 EDU 可开发版 ¥89,999**。
3. **SO-101 的 "$100 起" 不是成交价。** 官方 GitHub BOM 单臂 $121.94 / 双臂 $229.88（不含 3D 打印件、相机、电源）；Seeed 仅舵机套件 $249.90、组装单臂 $299、打印件另 $29.90；完整 leader–follower 遥操作要两只臂。WowRobo 基础档被经销商自己标注"不是完整系统"。
4. **WowRobo / OpenELAB 报价极度分散。** 官方经销页 2026-11-05 实取 €409.45 含税 / €344.08 未税（三档全部售罄、需预订）；thedynamics.ai 记 $199–$299；中文路线图记美站 $325.99/$419.99/$489.99；缓存曾显示 €310–€527.95。含税/未税 + 变体内容 + 渠道 + 时点四重差异，`priceUsd` 因此留 `null`，只用 `priceRange` 与 `note` 表达。
5. **RealSense 官网已提价，搜索引擎缓存失真。** 缓存 D435 $314 / D405 $272 / D435i $334；2026-11-05 WebFetch 官方商店实价 D435 **$375** / D405/D415 **$325** / D435i **$399**。官方对比页仍显示旧价。DigiKey（$322.50 / $278.75）与第三方店铺（$550 / $450）又各不同。本表采用**实时抓取值**并把旧价写入 `note`。
6. **树莓派 5 官方公告 vs 价格追踪站冲突。** 官方公告 4GB $70 / 8GB $95 / 16GB $145；raspberry.tips 记 2026-10 起 4GB $110 / 8GB $175 / 16GB $305，称因 LPDDR4 涨价一年内四次调价。`priceUsd` 取可实测的官方公告页，冲突完整写入 `note`，并提示以产品页当日价为准。
7. **Lambda 官方两页自相矛盾。** `/pricing` 记 1× A100 40GB **$1.99/GPU/hr**，`/service/gpu-cloud` 记 **$1.29/GPU/hr**；可能是 Instances 与 On-Demand 两套计费。仅作为参考写入 AutoDL 条目 `note`，未单列成条。
8. **云 GPU 媒体报价离散度大。** AutoDL 4090 官网 ¥1.88/时，媒体分别记 ¥1.58、¥2.38、¥2.8、¥3.98/时；差异来自地区、会员、促销、时点。本表一律以官网实时价为准。阿里云 A10(gn7i) 按量 ¥9.53–10.18/时是**4 卡整机**价，不能与单卡时租直接比较。
9. **国内消费卡价格全是"快照"，不是实时价。** diy52 三条均为 2026-05 京东自营促销到手价；同一 4090 因公版/涡轮/工包/48G 改卡/4090D 差 ¥17,499–31,200；淘宝 5090 同页出现 ¥33,999 常卖价、¥29,999 史低、¥55,599 另一标价。因此三条均标注"2026-05 媒体快照、非实时"，且不折算美元（3090 已停产无官方 MSRP）。
10. **六维力传感器价格跨越两个数量级。** 国产 MEMS 入门 ¥1,999（2026-05 发布价）、国产量产 ¥5,000–8,000、进口 ATI 2–8 万、定制 12–18 万；B2B 平台还存在 ¥2/台 这类询价占位价。`priceCny` 取最低的可核验发布价，其余全部进 `priceRange` 与 `note`。
11. **UMI 有两套完全不同的方案。** 斯坦福原版 BOM $73 + $298 ≈ $371（GoPro 方案）；UMI-3D 变体含 Livox MID-360 激光雷达，目标 ≈¥5,000（≈$700）。混用会严重低估预算。
12. **币种被转载写错。** LeRobot 论文 Table 1a 单位是**欧元**（~€225 / ~€550 / ~€670 / ~€1,346 / ~€21k / ~€230 / ~€500），部分中文转载直接写成"美元"，本表按论文原文保留 €。
13. **时间性风险。** 2026 年 LPDDR4/显存涨价导致树莓派、Seeed Jetson 整机（官方公告将上调 $50–$400）、消费显卡全部进入快速调价期；所有价格 `verifiedAt`=2026-11-05，超过一个月应重新核价。

**填 `null` 的字段说明**：`priceCny` 为 `null` 的条目多为只有美元/欧元官方报价、无可靠人民币成交价，按"宁缺勿假"不按汇率硬折；`priceUsd` 为 `null` 的条目多为国内电商人民币快照或欧元报价，不做反向换算。`priceRange` 为 `null` 的 4 条零成本项与 2 条单值项表示无区间。

---

## 五、三档预算建议（总预算区间）

> 均按人民币计；美元项按 1 USD ≈ 7.1 CNY 估量级。区间已包含隐性成本，但不包含运费、进口关税、增值税与工时。

### 档 A｜零硬件（tier=zero）
- 组成：Colab 免费层 + Kaggle 30h/周 + MuJoCo / Isaac Sim 纯仿真；可选 Hugging Face ZeroGPU 免费额度。
- **总预算：¥0**（纯免费路径）。
- 若需要更稳定的算力：加 AutoDL 按量 ¥1.32–2.78/时，按每周 10 小时计约 **¥55–120/月**； 存储/数据盘另计。
- 建议：**¥0 – ¥500/月**。适合先跑通 LeRobot 全流程、ACT/Diffusion Policy、sim2real 域随机化，一分钱硬件不买即可开工。

### 档 B｜消费级（starter/core，桌面真臂）
- 组成：SO-101 双臂遥操作套件（Seeed $249.90–299 或 WowRobo $199–489.99 ≈ **¥1,400–3,500**）+ 3D 打印件 $29.90（≈¥210）+ USB 摄像头 $12（≈¥85）+ 12 颗舵机备件/电源/桌夹/线材（≈**¥400–1,000**）+ 上位机（树莓派 5 4GB $70 ≈¥500，或 Jetson Orin Nano Super $249 ≈¥1,770）+ 云 GPU 训练 ¥100–500/月。
- **一次性硬件总预算：¥3,000 – ¥8,000**（用树莓派做上位机）；若上 Jetson Orin Nano Super，约 **¥5,000 – ¥10,000**。
- 加上云算力：**¥3,000 – ¥10,000 起步 + ¥100–500/月**。
- 想本地训练再补一张 RTX 3090（¥6,699）或 4090（¥21,799），但按 AutoDL ¥1.88/时计，买 4090 的钱约可租 11,600 小时，低频使用者不建议先买卡。

### 档 C｜有真机（pro，整机/人形/四足）
- **C1 入门真机：¥40,000 – ¥120,000**
  - Unitree R1 AIR ¥29,900（含税）/ R1 ¥39,900，或 Go2 EDU 可开发版 ¥89,999；
  - 加 UMI 手持采集夹爪（$371 ≈¥2,600 或 UMI-3D ≈¥5,000）+ RealSense D435/D405（$375+$325 ≈¥5,000）+ 上位机/工作站 + 云算力。
  - 注意：这个价位买到的是**基础/消费版**；要开放二次开发接口往往就是 EDU 版（Go2 EDU ¥89,999）。
- **C2 科研真机：¥250,000 – ¥600,000+**
  - G1 EDU 开发版（京东 ¥198,550–308,950，官网询价）+ 灵巧手（Dex5-S $6,350）+ 高算力模组（Orin 选配）+ 六维力传感器（单颗 ¥1,999–80,000，人形常需 4 颗）+ 本地 4090 工作站（¥21,799 卡 + 整机）。
  - 若选 ALOHA / Mobile ALOHA 双臂平台（$20,000–35,000 ≈ ¥14–25 万）另加集成工时，也落在这一档。
- 两档都不含：运费/关税、EDU 授权与保修升级、100–200 小时 ROS2/LeRobot 集成调试工时、失败打印件与备件。

---

## 六、最需要提醒的价格陷阱（结论）

**"起售价"买的往往是不能二次开发的展示机。** 宇树 `/g1/` 官方规格表白纸黑字：G1 基础版 `Secondary Development: /`、只有 G1 EDU 才是 `YES`；R1 官网把 `R1 EDU` 标成"联系销售"；Go2 消费版 ¥1.5–1.9 万，而 **Go2 EDU 可开发版 ¥89,999**。于是 `$13.5K G1` / `¥2.99万 R1` 只是"能走能跳"的入门价，真正能做具身智能研究的配置是 ¥20 万–30 万甚至更高，且不公开报价。同理，SO-101 的 "$100 起" 是单臂极限 DIY 口径，RealSense 官网价格已比搜索引擎缓存高约 20%，树莓派 5 官方公告价与 2026-10 挂牌价差近一倍——**下单前必须以官方产品页当日实时价 + 变体清单核对，而不是以宣传语、缓存快照或"起"字定价做预算。**
