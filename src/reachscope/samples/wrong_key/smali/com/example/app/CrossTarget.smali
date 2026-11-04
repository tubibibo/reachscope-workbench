.class public Lcom/example/app/CrossTarget;
.super Landroid/app/Activity;
.source "CrossTarget.java"

# v0.3 跨组件 fixture（目标）：未导出组件，从 Intent extra 取 URL 直接 loadUrl。
.method public onCreate(Landroid/os/Bundle;)V
    .locals 3

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    invoke-virtual {p0}, Lcom/example/app/CrossTarget;->getIntent()Landroid/content/Intent;
    move-result-object v1
    const-string v2, "url"
    invoke-virtual {v1, v2}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V
    return-void
.end method
