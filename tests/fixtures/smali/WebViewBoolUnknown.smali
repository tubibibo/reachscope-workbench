.class public Lcom/example/app/WebViewNoConstActivity;
.super Landroid/app/Activity;
.source "WebViewNoConstActivity.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

# 布尔值不是常量（来自字段），必须标 None，不能猜 True/False（D-016）
.method protected onCreate(Landroid/os/Bundle;)V
    .locals 3

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    invoke-virtual {v0}, Landroid/webkit/WebView;->getSettings()Landroid/webkit/WebSettings;
    move-result-object v1

    sget-boolean v2, Lcom/example/app/Config;->ENABLE_JS:Z
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setJavaScriptEnabled(Z)V

    const/4 v2, 0x1
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setAllowFileAccess(Z)V

    const-string v1, "https://static.example.com/index.html"
    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    return-void
.end method
