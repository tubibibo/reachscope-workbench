.class public Lcom/example/app/RegflowCallee;
.super Ljava/lang/Object;
.source "RegflowCallee.java"

# §6.1 跨方法：方法体 ≤ 80 条指令，进入一层并把返回值标签带回
.method public static make()Ljava/lang/String;
    .locals 1

    const-string v0, "callee"
    return-object v0
.end method

# 两层调用：host → viaMake → make。v0.1 只跟进一层，第二层必须 unknown + incomplete
.method public static viaMake()Ljava/lang/String;
    .locals 1

    invoke-static {}, Lcom/example/app/RegflowCallee;->make()Ljava/lang/String;
    move-result-object v0
    return-object v0
.end method

# 供 host 调用：走 viaMake 就是两层
.method public host()Ljava/lang/String;
    .locals 1

    invoke-static {}, Lcom/example/app/RegflowCallee;->viaMake()Ljava/lang/String;
    move-result-object v0
    return-object v0
.end method
