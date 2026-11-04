.class public Lcom/example/app/GuardedHostActivity;
.super Landroid/app/Activity;
.source "GuardedHostActivity.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 3

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    new-instance v1, Lcom/example/app/GuardedBridge;
    invoke-direct {v1, p0}, Lcom/example/app/GuardedBridge;-><init>(Landroid/content/Context;)V

    const-string v2, "guarded"

    invoke-virtual {v0, v1, v2}, Landroid/webkit/WebView;->addJavascriptInterface(Ljava/lang/Object;Ljava/lang/String;)V

    return-void
.end method
