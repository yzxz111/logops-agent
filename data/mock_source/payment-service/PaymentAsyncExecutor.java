package com.logops.pay;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

public class PaymentAsyncExecutor {
    // 队列容量 200，使用 AbortPolicy，下游阻塞时触发 RejectedExecutionException
    private final ThreadPoolExecutor payAsyncPool = new ThreadPoolExecutor(
            8, 16, 60L, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(200),
            new ThreadPoolExecutor.AbortPolicy()
    );

    public void submitRiskCheck(Runnable task) {
        payAsyncPool.submit(task);
    }
}
