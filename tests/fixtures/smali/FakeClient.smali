# 与回调同名但**不是** WebViewClient 体系的业务类：
# T2.5 的扫描范围必须把它排除在外，否则会把普通业务方法判成来源校验位置。
.class public Lcom/example/app/FakeClient;
.super Ljava/lang/Object;
.source "FakeClient.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

.method public shouldOverrideUrlLoading(Landroid/webkit/WebView;Ljava/lang/String;)Z
    .locals 1
    const/4 v0, 0x1
    return v0
.end method
