.class public Lcom/example/app/J5Bridge;
.super Ljava/lang/Object;
.source "J5Bridge.java"

.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

# 这就是 @JavascriptInterface 标注的方法，J5 在 onResume 里被调到它
.method public javascriptMethod(Ljava/lang/String;)V
    .locals 0

    .annotation runtime Landroid/webkit/JavascriptInterface;
    .end annotation

    return-void
.end method
