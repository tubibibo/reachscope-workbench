.class public Lcom/example/app/M1EntryBranch;
.super Landroid/app/Activity;
.source "M1EntryBranch.java"

# M1 判别矩阵（源入口 C）：
# onCreate → 两个分支分别 setClass 到不同组件，再 putExtra + startActivity
#            → 目标冲突，不应猜其中任何一个（不建链）
# onStart  → putExtra 之后寄存器被重新定义，再当 Intent 传给 startActivity
#            → 旧状态必须失效（不建链）

.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1EntryBranch;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    invoke-direct {v3}, Landroid/content/Intent;-><init>()V
    const-class v0, Lcom/example/app/CrossTarget;
    const-class v4, Lcom/example/app/M1DataTarget;
    const/4 v0, 0x0
    if-eqz v0, :cond_b
    const-class v0, Lcom/example/app/CrossTarget;
    invoke-virtual {v3, v0}, Landroid/content/Intent;->setClass(Landroid/content/Class;)Landroid/content/Intent;
    goto :done
    :cond_b
    invoke-virtual {v3, v4}, Landroid/content/Intent;->setClass(Landroid/content/Class;)Landroid/content/Intent;
    :done
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/M1EntryBranch;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onStart()V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1EntryBranch;->getIntent()Landroid/content/Intent;
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
    const-string v3, "register reused for a string"
    invoke-virtual {p0, v3}, Lcom/example/app/M1EntryBranch;->startActivity(Landroid/content/Intent;)V
    return-void
.end method
