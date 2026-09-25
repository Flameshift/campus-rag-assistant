package com.aiassistant.exceptionHandler;

import com.aiassistant.common.Result;
import com.aiassistant.common.ResultCode;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

/**
 * 全局异常处理器。
 *
 * 作用：把 Controller / Service 抛出的异常统一转换成 Result，
 * 避免前端拿到 Spring 默认错误结构导致解析不一致。
 */
@RestControllerAdvice
@Slf4j
public class GlobalExceptionHandler {

    /**
     * 处理业务异常：例如 AuthService 抛出的
     * ResponseStatusException(409, "用户名已存在")。
     * HTTP 状态码与业务码保持一致，前端可直接读取 msg。
     */
    @ExceptionHandler(ResponseStatusException.class)
    public Result<?> handleStatus(ResponseStatusException ex, HttpServletResponse response) {
        response.setStatus(ex.getStatusCode().value());
        return Result.error(
                String.valueOf(ex.getStatusCode().value()),
                ex.getReason() == null ? "操作失败" : ex.getReason(),
                null);
    }

    /**
     * 处理 @Valid 参数校验失败，例如用户名过短、密码少于 6 位。
     * 统一返回 400 + Result，前端可以直接展示 msg。
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public Result<?> handleValidation(MethodArgumentNotValidException ex, HttpServletResponse response) {
        response.setStatus(400);
        String message = ex.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(error -> error.getDefaultMessage() == null ? "参数校验失败" : error.getDefaultMessage())
                .orElse("参数校验失败");
        return Result.error("400", message, null);
    }

    /**
     * 兜底处理未知异常：记录日志并返回通用 500，避免把堆栈泄露给前端。
     */
    @ExceptionHandler(Exception.class)
    public Result<?> handleException(Exception e, HttpServletResponse response) {
        log.error("系统异常", e);
        response.setStatus(500);
        return Result.error(ResultCode.ERROR.getCode(), ResultCode.ERROR.getMsg(), null);
    }
}
