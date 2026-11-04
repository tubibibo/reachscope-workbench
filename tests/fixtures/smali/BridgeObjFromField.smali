.class public Lcom/example/app/FieldBridgeActivity;
.super Landroid/app/Activity;
.source "FieldBridgeActivity.java"

# 桥对象来自字段（不是 new-instance）→ impl_class 无法回溯，必须留空 + warning
.field private mBridge:Lcom/example/app/UnregisteredBridge;

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 3

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    iget-object v1, p0, Lcom/example/app/FieldBridgeActivity;->mBridge:Lcom/example/app/UnregisteredBridge;

    const-string v2, "fromField"

    invoke-virtual {v0, v1, v2}, Landroid/webkit/WebView;->addJavascriptInterface(Ljava/lang/Object;Ljava/lang/String;)V

    return-void
.end method
