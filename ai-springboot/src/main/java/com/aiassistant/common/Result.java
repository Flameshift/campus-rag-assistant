package com.aiassistant.common;

import lombok.Data;

/**
 * 统一响应包装类。
 *
 * 前端统一读取：
 * {
 *   "code": "200",   // 业务状态码
 *   "msg": "操作成功", // 提示信息
 *   "data": {...}     // 业务数据
 * }
 *
 * 约定：
 * - 网关透传接口（/api/chat、/api/upload、SSE）不做包装；
 * - 只有 Spring Boot 自身的业务接口使用 Result。
 */
@Data
public class Result<T> {

    /** 业务状态码：成功为 200，失败见 ResultCode。 */
    private String code;

    /** 给前端展示的提示信息。 */
    private String msg;

    /** 实际业务数据，可为 null。 */
    private T data;

    /** 只返回成功状态，不带业务数据。 */
    public static <T> Result<T> success() {
        Result<T> result = new Result<>();
        result.setCode(ResultCode.SUCCESS.getCode());
        result.setMsg(ResultCode.SUCCESS.getMsg());
        return result;
    }

    /** 成功并携带业务数据。 */
    public static <T> Result<T> success(T data) {
        Result<T> result = success();
        result.setData(data);
        return result;
    }

    /** 通用失败：使用 ResultCode.ERROR 的 code 与 msg。 */
    public static <T> Result<T> error() {
        Result<T> result = new Result<>();
        result.setCode(ResultCode.ERROR.getCode());
        result.setMsg(ResultCode.ERROR.getMsg());
        return result;
    }

    /** 自定义失败：指定业务码、提示信息与附加数据。 */
    public static <T> Result<T> error(String code, String msg, T data) {
        Result<T> result = new Result<>();
        result.setCode(code);
        result.setMsg(msg);
        result.setData(data);
        return result;
    }
}
