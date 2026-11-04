.class public Lcom/example/app/M1UnknownKey;
.super Landroid/app/Activity;
.source "M1UnknownKey.java"

# M1 不可判定：putExtra 的 key 本身来自攻击者（不是常量）→ 无法判定是否与
# 目标侧读取的 "url" 是同一个 key。链要保留，但 evidence_complete=False。
.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1UnknownKey;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "key"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/CrossTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {v3, v2, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1UnknownKey;->startActivity(Landroid/content/Intent;)V
    return-void
.end method
