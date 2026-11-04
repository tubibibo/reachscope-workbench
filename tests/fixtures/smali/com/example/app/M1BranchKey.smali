.class public Lcom/example/app/M1BranchKey;
.super Landroid/app/Activity;
.source "M1BranchKey.java"

# M1 判别矩阵（源入口 D）：寄存器跨分支复用（OVAA 形状）。
# key 在入口处定义为 "url"；另一个分支复用同一个寄存器放别的字符串并跳走，
# 到不了 putExtra。线性扫描会把它当成最后一次定义 → key 未知；
# 到达定义分析应恢复 "url"。

.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1BranchKey;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v3

    const-string v2, "url"
    const/4 v0, 0x0
    if-eqz v0, :cond_webview
    const-string v2, "grant"
    goto :done
    :cond_webview
    new-instance v4, Landroid/content/Intent;
    const-class v0, Lcom/example/app/CrossTarget;
    invoke-direct {v4, p0, v0}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {v4, v2, v3}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v4}, Lcom/example/app/M1BranchKey;->startActivity(Landroid/content/Intent;)V
    :done
    return-void
.end method
