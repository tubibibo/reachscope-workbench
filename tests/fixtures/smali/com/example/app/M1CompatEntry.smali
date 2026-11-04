.class public Lcom/example/app/M1CompatEntry;
.super Landroid/app/Activity;
.source "M1CompatEntry.java"

# M1 判别矩阵（源入口 E）：
# onCreate    → ContextCompat.startActivity(...)                → 应建链（静态包装）
# onStart     → helper(可控 url)，helper 内构造 Intent + startActivity → 应建链（过程间污点）
# onNewIntent → helper(常量)                                   → 不应建链（形参来自常量）

.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/M1CompatEntry;->getIntent()Landroid/content/Intent;
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
    invoke-static {p0, v3}, Landroidx/core/content/ContextCompat;->startActivity(Landroid/content/Context;Landroid/content/Intent;)V
    return-void
.end method

.method public onStart()V
    .locals 2

    invoke-virtual {p0}, Lcom/example/app/M1CompatEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1
    invoke-direct {p0, v1}, Lcom/example/app/M1CompatEntry;->launchUrl(Ljava/lang/String;)V
    return-void
.end method

.method public onNewIntent(Landroid/content/Intent;)V
    .locals 1

    const-string v0, "https://safe.example.com/"
    invoke-direct {p0, v0}, Lcom/example/app/M1CompatEntry;->launchUrl(Ljava/lang/String;)V
    return-void
.end method

.method private launchUrl(Ljava/lang/String;)V
    .locals 3

    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/example/app/CrossTarget;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    const-string v2, "url"
    invoke-virtual {v0, v2, p1}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v0}, Lcom/example/app/M1CompatEntry;->startActivity(Landroid/content/Intent;)V
    return-void
.end method
