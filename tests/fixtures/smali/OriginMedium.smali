.class public Lcom/example/app/MediumClient;
.super Landroid/webkit/WebViewClient;
.source "MediumClient.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/webkit/WebViewClient;-><init>()V
    return-void
.end method

# medium 例 1：原始 URL 字符串参与 equals（不是 getHost）
.method public shouldOverrideUrlLoading(Landroid/webkit/WebView;Ljava/lang/String;)Z
    .locals 3

    const-string v0, "https://example.com/open"

    invoke-virtual {v0, p2}, Ljava/lang/String;->equals(Ljava/lang/Object;)Z

    move-result v1

    if-eqz v1, :cond_deny

    const/4 v1, 0x0
    return v1

    :cond_deny
    const/4 v1, 0x1
    return v1
.end method

# medium 例 2：getHost 参与 startsWith / endsWith
.method public onPageStarted(Landroid/webkit/WebView;Ljava/lang/String;Landroid/graphics/Bitmap;)V
    .locals 3

    invoke-static {p2}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v0

    invoke-virtual {v0}, Landroid/net/Uri;->getHost()Ljava/lang/String;
    move-result-object v0

    const-string v1, "example.com"

    invoke-virtual {v0, v1}, Ljava/lang/String;->startsWith(Ljava/lang/String;)Z

    move-result v2

    if-eqz v2, :cond_ok

    return-void

    :cond_ok
    return-void
.end method
