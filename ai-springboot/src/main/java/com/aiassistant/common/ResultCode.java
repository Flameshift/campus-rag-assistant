package com.aiassistant.common;

/**
 * 业务状态码枚举。
 *
 * code 用于前端判断成功/失败，msg 是默认提示信息。
 * 建议错误码按模块分段：用户模块 1000+、会话模块 2000+、知识库模块 3000+。
 */
public enum ResultCode {

    /** 操作成功。 */
    SUCCESS("200", "操作成功"),

    /** 未分类的通用失败。 */
    ERROR("-1", "操作失败"),

    /** 未登录或登录已过期。 */
    UNAUTHORIZED("401", "未登录或登录已过期"),

    /** 请求的资源不存在。 */
    NOT_FOUND("404", "资源不存在"),

    /** 注册时用户名已被占用。 */
    USERNAME_EXISTS("1001", "用户名已存在");

    /** 业务状态码。 */
    private final String code;

    /** 默认提示信息。 */
    private final String msg;

    ResultCode(String code, String msg) {
        this.code = code;
        this.msg = msg;
    }

    public String getCode() {
        return code;
    }

    public String getMsg() {
        return msg;
    }
}
