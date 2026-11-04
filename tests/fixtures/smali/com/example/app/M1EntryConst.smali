.class public Lcom/example/app/M1EntryConst;
.super Landroid/app/Activity;
.source "M1EntryConst.java"

# M1 判别矩阵（源入口 B）：
# onCreate  → putExtra("url", 常量)                     → 不应建链（来源不是攻击者）
# onStart   → 本地 new Intent 上 getStringExtra("url") → 不应建链（不是入口 Intent）

.method public onCreate(Landroid/os/Bundle;)V
    .locals 4

    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/example/app/CrossTarget;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    const-string v2, "url"
    const-string v3, "https://safe.example.com/"
    invoke-virtual {v0, v2, v3}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Lcom/example/app/M1EntryConst;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onStart()V
    .locals 4

    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/example/app/CrossTarget;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/content/Intent;->getStringExtra(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2
    invoke-virtual {v0, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Lcom/example/app/M1EntryConst;->startActivity(Landroid/content/Intent;)V
    return-void
.end method
