.class public Lcom/example/app/CrossDeadEnd;
.super Landroid/app/Activity;
.source "CrossDeadEnd.java"

# M1 反例：入口把攻击者数据写进显式 Intent，但目标组件没有任何 sink。
.method public onCreate(Landroid/os/Bundle;)V
    .locals 4

    invoke-virtual {p0}, Lcom/example/app/CrossDeadEnd;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v0, Lcom/example/app/DeadEndTarget;
    invoke-direct {v3, p0, v0}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/CrossDeadEnd;->startActivity(Landroid/content/Intent;)V
    return-void
.end method
