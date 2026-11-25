---
doc_id: KB-025
title: 下游 HTTPS/TLS 证书过期导致 PKIX 校验失败
service: gateway
error_code: TLS-CERT-EXPIRED
severity: P0
keywords: PKIX path building failed, SSLHandshakeException, CertificateExpiredException, TLS, 证书过期
---
# 下游 HTTPS/TLS 证书过期导致 PKIX 校验失败

## 现象描述
网关调用外部合作方或内部 mTLS 下游时全量报错 `javax.net.ssl.SSLHandshakeException: PKIX path validation failed: java.security.cert.CertPathValidatorException: timestamp check failed` 或 `CertificateExpiredException`。

## 根因分析
1. 对端服务器 SSL 证书已过有效期未及时续签，或中间 CA 证书链未配置完整。
2. 客户端 JVM `cacerts` 信任库未导入自签根证书。

## 排查步骤
1. 检索 `gateway` 日志中的 `SSLHandshakeException`、`PKIX` 或 `CertificateExpiredException`。
2. 确认证书过期的目标域名与端口，核对证书失效时间戳。

## 修复与高危操作提示
- 联系证书管理方更新有效 TLS 证书并导入完整证书链至 `truststore`。
- 高危操作（需人工确认）：**禁止在生产代码中配置 TrustAllManager 跳过 SSL 证书校验**（关闭 TLS 校验会引入中间人攻击高危漏洞），若临时应急必须经过安全人工审批。
