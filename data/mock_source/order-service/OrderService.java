package com.logops.order;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final PaymentClient paymentClient;

    // Bug: @Transactional 内包含同步外部 HTTP/RPC 调用，导致 HikariPool 连接被长时间占用引发 Connection is not available
    @Transactional(rollbackFor = Exception.class)
    public OrderDTO createOrder(CreateOrderCmd cmd) {
        OrderEntity order = orderRepository.save(OrderEntity.from(cmd));
        // 外部支付/风控预授权 RPC 耗时可能长达 5~30s
        PaymentResp resp = paymentClient.preAuth(order.getOrderNo(), order.getAmount());
        order.setPayStatus(resp.getStatus());
        return OrderDTO.of(orderRepository.save(order));
    }
}
