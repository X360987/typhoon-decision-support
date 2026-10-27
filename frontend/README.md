# 前端（Vue 3 + TypeScript + Vite）

台风灾害分析平台的前端。整体说明、接口与验收记录见上级目录 [README](../README.md)。

```bash
npm install
npm run dev      # http://localhost:5173，默认请求 http://localhost:8000
npm test         # vitest 交互测试（jsdom，接口全部 mock）
npm run build    # vue-tsc 类型检查 + 生产构建
npm run e2e      # 浏览器冒烟：需先启动后端（demo）与 dev server，使用本机 Edge/Chrome
```

环境变量（`frontend/.env`，均为公开配置）：

- `VITE_API_BASE`：后端地址，默认 `http://localhost:8000`
- `VITE_TIANDITU_TK`：天地图影像底图密钥（可选）

写操作密钥不放进构建产物，由用户在“数据管理 › 写操作凭证”填写，只保存在当前标签页。

结构：

- `src/stores/context.ts`：全站共享查询上下文（数据集、事件、省份、回放模式、分析时刻、数据版本）
- `src/composables/useLoader.ts`：带序号与取消的数据加载；切换事件时清空旧数据
- `src/views/`：事件总览、影响事件与行动、历史回放、分析中心、预测中心、异常与证据、数据管理、资料与口径
- `src/components/`：趋势图、省级地图、时间轴、状态提示等
- `tests/`：回放截断、预测未来横轴、证据核验、导入阻断、快速切换上下文
- `scripts/`：浏览器冒烟脚本
