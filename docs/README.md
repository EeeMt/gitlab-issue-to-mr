# Documentation Index

This directory aggregates the main project documentation. Start from the root [README](../README.md) for an overview, then use the guides below for specific tasks.

## 入门与使用

- [中文入门与使用指南](README.zh-CN.md) — 产品概览、快速开始、Dashboard 使用、配置项与 FAQ

## 部署与运维

- [生产部署指南](DEPLOYMENT.md) — 部署目标、更新、备份、排障、升级回滚
- [GitLab OIDC 登录配置](GITLAB_OIDC_SETUP.md)
- [内网离线迁移实施方案](OFFLINE-DEV.md) — 无公网环境的开发/构建/测试/部署
- [日志追踪方案](LOGGING.md) — 前后端 Trace ID 全链路日志定位

## 开发环境

- [开发环境搭建指南](DEVELOPMENT.md)
- [开发环境核心功能回归计划](dev-env-core-regression.md) — 分层（冒烟/完整/发版演练）核心链路回归
- [开发环境 API 回归验证手册](dev-env-api-regression.md) — Phase 1 L4 API 级验证步骤与已知问题

## 测试

- [测试指南](TESTING.md) — 所有测试类型的运行总览
- [E2E 测试指南](E2E_TESTS.md) — Playwright 编写/运行/调试 + GitLab 集成验证

## Worker

- [Mounted Worker Kits](worker-kits.md) — worker 交付模式（Kit 挂载 vs 烘焙镜像）
- [Worker Volume Mounts](worker-volume-mounts.md) — 独立运行时镜像的卷挂载梳理

## 架构与设计

- [Worker Harness Adapter 契约 v1](architecture/worker-harness-contract-v1.md)
- [Worker Canonical Event v1](architecture/worker-canonical-event-v1.md)
- [Issue Task 有序回合设计与实施方案](superpowers/specs/2026-08-08-issue-task-ordered-turns-design.md) — 将同一 Issue 建模为严格有序的交互式 CLI 输入流
- [Multi-Harness 接入调试与通用经验](multi-harness-debugging.md) — 通用接入断层清单（含 codex 专项）与验证命令

## 安全

- [模型凭据交付方式：受限 legacy 风险接受](security/credential-delivery-risk-acceptance.md)

## Runbooks

- [Multi-Harness 切换与生产验收 Runbook](runbooks/multi-harness-rollout.md)
- [Multi-Harness 验收证据模板](runbooks/multi-harness-rollout-evidence.md)

## Review 档案

- [2026-08-07 Multi-Harness 深度 Review](reviews/2026-08-07-multi-harness-deep-review.md)
- [Multi-Harness 架构评审纪要](reviews/multi-harness-architecture.md)

---

> 设计文档与阶段计划见 [`superpowers/`](superpowers/)（plans = 实施计划，specs = 设计文档），作为历史决策档案保留。
