package com.logops.inventory;

import java.util.concurrent.TimeUnit;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;

public class InventoryLockService {
    private final RedissonClient redissonClient;

    public void deductWithLock(String skuId, int count) throws InterruptedException {
        RLock lock = redissonClient.getLock("lock:sku:" + skuId);
        // Bug: 传入正数 leaseTime=5 秒导致 Redisson WatchDog 自动续期失效，超时后触发 IllegalMonitorStateException
        if (lock.tryLock(3, 5, TimeUnit.SECONDS)) {
            try {
                doDeductInventory(skuId, count);
            } finally {
                // 未检查 lock.isHeldByCurrentThread()
                lock.unlock();
            }
        }
    }

    private void doDeductInventory(String skuId, int count) {
        // 扣减库存数据库操作
    }
}
