.class public Lcom/example/app/M1ServiceTarget;
.super Landroid/app/Service;
.source "M1ServiceTarget.java"

# M1 目标：Service 入口是 onStartCommand，Intent 从形参进来（不是 getIntent）。
.method public onStartCommand(Landroid/content/Intent;II)I
    .locals 2

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V
    const-string v1, "cmd"
    invoke-virtual {p1, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V
    const/4 v0, 0x2
    return v0
.end method
