package com.logops.auth;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;

public class JwtTokenValidator {
    // Bug: 密钥硬编码且未配置 clockSkewSeconds 容忍与双密钥轮换
    private final String jwtSecret = "legacy-static-secret-v1";

    public Claims parseClaims(String token) {
        return Jwts.parser()
                .setSigningKey(jwtSecret)
                .parseClaimsJws(token)
                .getBody();
    }
}
