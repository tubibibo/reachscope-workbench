.class public Lcom/example/app/WeakClient;
.super Landroid/webkit/WebViewClient;
.source "WeakClient.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/webkit/WebViewClient;-><init>()V
    return-void
.end method

# weak：contains 直接作用在完整 URL 上（evil.com/?x=example.com 可绕过）
.method public shouldOverrideUrlLoading(Landroid/webkit/WebView;Ljava/lang/String;)Z
    .locals 3

    const-string v0, "example.com"

    invoke-virtual {p2, v0}, Ljava/lang/String;->contains(Ljava/lang/CharSequence;)Z

    move-result v1

    if-eqz v1, :cond_deny

    const/4 v1, 0x0
    return v1

    :cond_deny
    const/4 v1, 0x1
    return v1
.end method
