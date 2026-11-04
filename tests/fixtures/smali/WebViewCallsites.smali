.class public Lcom/example/app/WebViewHostActivity;
.super Landroid/app/Activity;
.source "WebViewHostActivity.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/app/Activity;-><init>()V
    return-void
.end method

.method protected onCreate(Landroid/os/Bundle;)V
    .locals 4

    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    invoke-virtual {v0}, Landroid/webkit/WebView;->getSettings()Landroid/webkit/WebSettings;
    move-result-object v1

    # 1~3：三个布尔开关（setJavaScriptEnabled / setAllowFileAccess /
    #      setAllowUniversalAccessFromFileURLs）
    const/4 v2, 0x1
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setJavaScriptEnabled(Z)V

    const/4 v2, 0x1
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setAllowFileAccess(Z)V

    const/4 v2, 0x0
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setAllowUniversalAccessFromFileURLs(Z)V

    # 4：setAllowFileAccessFromFileURLs（与上一项同档，最后一次生效 → false）
    const/4 v2, 0x0
    invoke-virtual {v1, v2}, Landroid/webkit/WebSettings;->setAllowFileAccessFromFileURLs(Z)V

    # 5~6：注册与撤销桥
    new-instance v1, Lcom/example/app/JsBridge;
    invoke-direct {v1, p0}, Lcom/example/app/JsBridge;-><init>(Landroid/content/Context;)V
    const-string v2, "native"
    invoke-virtual {v0, v1, v2}, Landroid/webkit/WebView;->addJavascriptInterface(Ljava/lang/Object;Ljava/lang/String;)V

    const-string v2, "debug"
    invoke-virtual {v0, v2}, Landroid/webkit/WebView;->removeJavascriptInterface(Ljava/lang/String;)V

    # 7：loadUrl(String) —— URL 来自 Intent.getData → toString
    invoke-virtual {p0}, Lcom/example/app/WebViewHostActivity;->getIntent()Landroid/content/Intent;
    move-result-object v1
    invoke-virtual {v1}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v1
    invoke-virtual {v1}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V

    # 8：loadUrl(String, Map)
    new-instance v1, Ljava/util/HashMap;
    invoke-direct {v1}, Ljava/util/HashMap;-><init>()V
    const-string v2, "https://cdn.example.com/page.html"
    invoke-virtual {v0, v2, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;Ljava/util/Map;)V

    # 9：loadData
    const-string v1, "<html>hi</html>"
    const-string v2, "text/html"
    const-string v3, "utf-8"
    invoke-virtual {v0, v1, v2, v3}, Landroid/webkit/WebView;->loadData(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V

    # 10：loadDataWithBaseURL
    const-string v1, "https://base.example.com/"
    const-string v2, "<html>hi</html>"
    const-string v3, "text/html"
    const-string v0, "utf-8"
    invoke-virtual {v0, v1, v2, v3}, Landroid/webkit/WebView;->loadDataWithBaseURL(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V

    return-void
.end method
