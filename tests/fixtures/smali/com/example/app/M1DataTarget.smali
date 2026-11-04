.class public Lcom/example/app/M1DataTarget;
.super Landroid/app/Activity;
.source "M1DataTarget.java"

# M1 目标：只读取 Intent data（Uri），不读 extra。
.method public onCreate(Landroid/os/Bundle;)V
    .locals 3

    new-instance v0, Landroid/webkit/WebView;
    invoke-direct {v0, p0}, Landroid/webkit/WebView;-><init>(Landroid/content/Context;)V

    invoke-virtual {p0}, Lcom/example/app/M1DataTarget;->getIntent()Landroid/content/Intent;
    move-result-object v1
    invoke-virtual {v1}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v1
    const-string v2, "url"
    invoke-virtual {v1, v2}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    invoke-virtual {v0, v1}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V
    return-void
.end method
