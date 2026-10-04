# Telegram → Bark Monitor

一个轻量的 Telegram 频道监听器：

```text
Telegram 频道
    ↓
你的 Telegram 账号（Telethon）
    ↓
关键词过滤
    ↓
SQLite 去重
    ↓
Bark
    ↓
iPhone 推送
```

## 功能

- Telegram 用户账号登录
- 支持多个频道
- 支持公开频道 `@username`
- 支持已加入的私有频道/群组（可用数字 ID）
- 全量推送 / 关键词过滤
- SQLite 消息去重
- Bark 标题、声音、分组、点击跳转
- Docker Compose
- 可选 Telegram SOCKS5 代理
- Session 持久化，首次登录后无需反复验证码

## 1. 获取 Telegram API ID / API HASH

打开：

https://my.telegram.org

进入：

`API development tools`

申请示例：



```
App title:
BarkMonitor

Short name:
barkmonitor12321

URL:
留空

Platform:
Desktop

Description:
Telegram channel monitor for personal use 
```

创建应用，得到：

- API ID
- API HASH

API HASH 是敏感凭据，不要提交到 GitHub。

## 2. 配置

复制：

```bash
copy .env.example .env
```

然后编辑 `.env`：

```env
TG_API_ID=12345678
TG_API_HASH=xxxxxxxxxxxxxxxxxxxxxxxx
TG_PHONE=+81xxxxxxxxxx

BARK_URL=https://api.day.app
BARK_KEY=xxxxxxxxxxxxxxxx

CHANNELS=@channel1,@channel2

FILTER_MODE=keyword
KEYWORDS=Alpha,空投,活动,免费,白嫖
```

如果想监控所有消息：

```env
FILTER_MODE=all
```

## 3. 第一次登录

推荐：

```bash
docker compose run --rm telegram-bark python main.py --login
```

容器会在终端询问：

```text
请输入 Telegram 登录验证码:
```

如果账号开启了两步验证，还会继续询问：

```text
请输入 Telegram 两步验证密码:
```

登录成功后：

```text
./data/telegram.session
```

会被保存。

以后不需要再次输入验证码。

## 4. 正式启动

```bash
docker compose up -d --build
```

查看日志：

```bash
docker logs -f telegram-bark-monitor
```

停止：

```bash
docker compose down
```

重启：

```bash
docker compose restart
```

## 5. Bark

默认接口：

```text
https://api.day.app
```

`.env`：

```env
BARK_KEY=你的设备Key
BARK_SOUND=telegraph
BARK_GROUP=Telegram
BARK_LEVEL=active
```

收到 Telegram 消息后会推送：

```text
【TG】频道名称

消息内容……

点击通知可以打开对应 Telegram 消息。
```

## 6. 关键词

例如：

```env
KEYWORDS=Alpha,空投,活动,免费,白嫖,抽奖,送U
```

程序采用“包含匹配”。

例如关键词：

```text
Alpha
```

以下消息都会匹配：

```text
Binance Alpha
Alpha 新活动
Alpha空投
```

## 7. Telegram 代理

如果服务器/Docker 无法直接访问 Telegram，可以设置：

```env
TELEGRAM_PROXY=socks5://127.0.0.1:10808
```

注意：

`127.0.0.1` 指的是容器本身，不是 Windows 主机。

如果代理运行在 Windows 主机，需要根据 Docker Desktop 网络情况使用主机地址，例如：

```env
TELEGRAM_PROXY=socks5://host.docker.internal:10808
```

如果 10808 是 HTTP 代理而不是 SOCKS5，需要使用：

```env
TELEGRAM_PROXY=http://host.docker.internal:10808
```

## 安全

不要公开：

- `.env`
- `telegram.session`
- `TG_API_HASH`
- `BARK_KEY`

尤其是：

```text
telegram.session
```

它相当于已经授权的 Telegram 登录凭据。

不要上传到 GitHub。

## 免责声明

这个项目使用 Telegram 用户账号通过 MTProto/Telethon 接收消息。请遵守 Telegram API 条款，不要用于刷屏、垃圾消息或其他滥用行为。
