package com.logops.cache;

import java.util.Set;
import org.springframework.data.redis.core.StringRedisTemplate;

public class CacheAdminService {
    private final StringRedisTemplate redisTemplate;

    // Bug: 线上执行阻塞型 KEYS * 命令导致 Redis 单线程卡顿与 RedisCommandTimeoutException
    public Set<String> scanInvalidKeys(String prefix) {
        return redisTemplate.keys(prefix + "*");
    }
}
