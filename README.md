# Grok Imagine Studio

一个本地网页工作台，可输入你的 xAI API Key，调用：

- `grok-imagine-image`
- `grok-imagine-video`

支持：

- 文生图
- 图片编辑（上传图片或填源图 URL）
- 多图编辑（最多 5 张参考图，自动走 `/v1/images/edits` 的 `images[]`）
- 文生视频
- 图生视频（单张首帧）
- 参考图生视频（`reference_images`，最多 5 张；与首帧图互斥）
- 视频扩展（`/v1/videos/extensions`）
- 多 API Key 管理
- 浏览器 `localStorage` 永久保存 Key（刷新不丢）

## 启动

```bash
python3 server.py
```

默认地址：

```text
http://127.0.0.1:8000
```

也可以自定义端口：

```bash
python3 server.py 9000
```

## 说明

- 页面不会把 API Key 写入服务器文件。
- Key 会保存在你当前浏览器的 `localStorage` 中，因此刷新页面不会丢。
- 支持保存多个 Key、切换当前 Key、批量导入。
- Key 只会随当前请求转发到 xAI API。
- 视频生成是异步流程：先拿到 `request_id`，再轮询状态直到 `done`。
- 视频扩展需要提供可访问的 `.mp4` URL；扩展片段时长支持 2-10 秒。
- 视频生成或扩展完成后，可直接点击结果卡片里的“直接扩展这个视频”，把上一条结果一键带入扩展表单。

## 参考文档

- https://docs.x.ai/developers/model-capabilities/images/generation
- https://docs.x.ai/developers/model-capabilities/video/generation
