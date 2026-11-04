.class public Lcom/example/app/M1ReceiverTarget;
.super Landroid/content/BroadcastReceiver;
.source "M1ReceiverTarget.java"

# M1 目标：Receiver 入口是 onReceive，Intent 是第 2 个形参（p2）。
.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .locals 2

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p1}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V
    const-string v1, "url"
    invoke-virtual {p2, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V
    return-void
.end method
