.class public Lcom/example/app/ChainEntry;
.super Ljava/lang/Object;
.source "ChainEntry.java"

# onCreate：deeplink → 桥方法 takeAndWrite（j5 会命中）→ 桥方法体里有 file sink
# onStart：只 log，不生成链（“连不通”负例）
# onNewIntent：和 onCreate 一样调用，用于验证去重
.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    new-instance v2, Landroid/webkit/WebView;
    invoke-direct {v2, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    invoke-virtual {p0}, Lcom/example/app/ChainEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0

    new-instance v1, Lcom/example/app/ChainBridge;
    invoke-direct {v1}, Lcom/example/app/ChainBridge;-><init>()V
    const-string v3, "bridge"
    invoke-virtual {v2, v1, v3}, Landroid/webkit/WebView;->addJavascriptInterface(Ljava/lang/Object;Ljava/lang/String;)V

    invoke-virtual {v1, v0}, Lcom/example/app/ChainBridge;->takeAndWrite(Ljava/lang/String;)V
    invoke-virtual {v1, v0}, Lcom/example/app/ChainBridge;->takeAndWrite(Ljava/lang/String;)V
    return-void
.end method

.method public onStart()V
    .locals 3

    invoke-virtual {p0}, Lcom/example/app/ChainEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {v0}, Ljava/lang/Object;->toString()Ljava/lang/String;
    move-result-object v0
    const-string v1, "tag"
    invoke-static {v1, v0}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public onNewIntent(Landroid/content/Intent;)V
    .locals 5

    new-instance v2, Landroid/webkit/WebView;
    invoke-direct {v2, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    invoke-virtual {p0, p1}, Lcom/example/app/ChainEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0

    new-instance v1, Lcom/example/app/ChainBridge;
    invoke-direct {v1}, Lcom/example/app/ChainBridge;-><init>()V
    const-string v3, "bridge"
    invoke-virtual {v2, v1, v3}, Landroid/webkit/WebView;->addJavascriptInterface(Ljava/lang/Object;Ljava/lang/String;)V

    invoke-virtual {v1, v0}, Lcom/example/app/ChainBridge;->takeAndWrite(Ljava/lang/String;)V
    return-void
.end method

.method public getIntent()Landroid/content/Intent;
    .locals 1
    const v0, 0x0
    return-object v0
.end method
