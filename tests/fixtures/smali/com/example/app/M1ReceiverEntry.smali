.class public Lcom/example/app/M1ReceiverEntry;
.super Landroid/app/Activity;
.source "M1ReceiverEntry.java"

# M1 判别矩阵（源入口 F）：
# onCreate → sendBroadcast(Intent(ctx, M1ReceiverTarget)) + 可控 extra → 应建链
# onStart  → sendOrderedBroadcast(...)                              → 应建链
# onResume → startService(Intent(ctx, M1ReceiverTarget))            → 不应建链（类型不符）

.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1ReceiverEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/M1ReceiverTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1ReceiverEntry;->sendBroadcast(Landroid/content/Intent;)V
    return-void
.end method

.method public onStart()V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1ReceiverEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/M1ReceiverTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    const/4 v4, 0x0
    invoke-virtual {p0, v3, v4}, Lcom/example/app/M1ReceiverEntry;->sendOrderedBroadcast(Landroid/content/Intent;Ljava/lang/String;)V
    return-void
.end method

.method public onResume()V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1ReceiverEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/M1ReceiverTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1ReceiverEntry;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;
    return-void
.end method
