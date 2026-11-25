package com.logops.order;

import java.util.List;

public class OrderExportService {
    private final OrderRepository orderRepository;

    // Bug: 未采用游标分页导出，直接全表查出加载到 ArrayList 引发 OutOfMemoryError: Java heap space
    public byte[] exportAllOrders(String tenantId) {
        List<OrderEntity> allRows = orderRepository.findAllByTenantId(tenantId);
        return CsvBuilder.render(allRows);
    }
}
