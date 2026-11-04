# 有 @JavascriptInterface 方法，但**从未**被 addJavascriptInterface 注册：
# 按 D-043 不产出 Bridge，只记 warning（可能是反射注册，不能静默丢掉线索）。
.class public Lcom/example/app/UnregisteredBridge;
.super Ljava/lang/Object;
.source "UnregisteredBridge.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public secret()Ljava/lang/String;
    .locals 1
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    const-string v0, "secret"
    return-object v0
.end method
