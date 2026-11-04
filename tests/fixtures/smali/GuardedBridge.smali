.class public Lcom/example/app/GuardedBridge;
.super Ljava/lang/Object;
.source "GuardedBridge.java"

.method public constructor <init>(Landroid/content/Context;)V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

# 桥方法**自带**来源校验 → location=bridge_method、effective=true、guarded=true
.method public open(Ljava/lang/String;)V
    .locals 4
    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    invoke-static {p1}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v0

    invoke-virtual {v0}, Landroid/net/Uri;->getHost()Ljava/lang/String;
    move-result-object v0

    const-string v1, "example.com"

    invoke-virtual {v0, v1}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v2

    if-eqz v2, :cond_ok

    return-void

    :cond_ok
    return-void
.end method
