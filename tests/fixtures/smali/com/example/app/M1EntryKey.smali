.class public Lcom/example/app/M1EntryKey;
.super Landroid/app/Activity;
.source "M1EntryKey.java"

# M1 判别矩阵（源入口 A）：
# onCreate     → putExtra("note")，目标读 "url"          → 不应建链（key 不匹配）
# onStart      → putExtra("url")，目标读 "url"           → 应建链
# onNewIntent  → setData(Uri.parse(可控))，目标读 getData → 应建链（data 载体）
# onResume     → putExtra("url", 本地常量)               → 不应建链（来源不是攻击者）

.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1EntryKey;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/CrossTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    const-string v1, "note"
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1EntryKey;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onStart()V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1EntryKey;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v4, Lcom/example/app/CrossTarget;
    invoke-direct {v3, p0, v4}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1EntryKey;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onNewIntent(Landroid/content/Intent;)V
    .locals 4

    invoke-virtual {p0}, Lcom/example/app/M1EntryKey;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    const-class v0, Lcom/example/app/M1DataTarget;
    invoke-direct {v3, p0, v0}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-static {v2}, Landroid/net/Uri;->parse(Ljava/lang/String;)Landroid/net/Uri;
    move-result-object v2
    invoke-virtual {v3, v2}, Landroid/content/Intent;->setData(Landroid/net/Uri;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1EntryKey;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onResume()V
    .locals 4

    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/example/app/CrossTarget;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    const-string v2, "url"
    const-string v3, "https://safe.example.com/"
    invoke-virtual {v0, v2, v3}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Lcom/example/app/M1EntryKey;->startActivity(Landroid/content/Intent;)V
    return-void
.end method
