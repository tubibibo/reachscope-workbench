.class public Lcom/example/app/HostClient;
.super Landroid/webkit/WebViewClient;
.source "HostClient.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Landroid/webkit/WebViewClient;-><init>()V
    return-void
.end method

# 11~13：三个回调声明（shouldOverrideUrlLoading / onPageStarted / onPageFinished）
.method public shouldOverrideUrlLoading(Landroid/webkit/WebView;Ljava/lang/String;)Z
    .locals 1
    const/4 v0, 0x0
    return v0
.end method

.method public onPageStarted(Landroid/webkit/WebView;Ljava/lang/String;Landroid/graphics/Bitmap;)V
    .locals 0
    return-void
.end method

.method public onPageFinished(Landroid/webkit/WebView;Ljava/lang/String;)V
    .locals 0
    return-void
.end method
