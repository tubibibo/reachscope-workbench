.class public Lcom/example/app/J5Entry;
.super Ljava/lang/Object;
.source "J5Entry.java"

# §6.3 J5 的 fixture：onCreate / onStart / onResume 三种入口
# onCreate：deeplink → loadUrl   → j5=True
# onStart： deeplink → Log.d     → j5=False（参数只进日志，不进 sink）
# onResume：deeplink → 桥方法    → j5=True
.method public onCreate(Landroid/os/Bundle;)V
    .locals 2

    invoke-virtual {p0}, Lcom/example/app/J5Entry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v1
    invoke-virtual {p0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V
    return-void
.end method

.method public onStart()V
    .locals 3

    invoke-virtual {p0}, Lcom/example/app/J5Entry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {v0}, Ljava/lang/Object;->toString()Ljava/lang/String;
    move-result-object v0
    const-string v1, "tag"
    invoke-static {v1, v0}, Landroid/util/Log;->d(Ljava/lang/String;Ljava/lang/String;)I
    return-void
.end method

.method public onResume()V
    .locals 3

    invoke-virtual {p0}, Lcom/example/app/J5Entry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    new-instance v1, Lcom/example/app/J5Bridge;
    invoke-direct {v1}, Lcom/example/app/J5Bridge;-><init>()V
    invoke-virtual {v1, v0}, Lcom/example/app/J5Bridge;->javascriptMethod(Ljava/lang/String;)V
    return-void
.end method

.method public getIntent()Landroid/content/Intent;
    .locals 1

    const v0, 0x0
    return-object v0
.end method
