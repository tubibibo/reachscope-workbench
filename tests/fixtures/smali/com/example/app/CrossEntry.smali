.class public Lcom/example/app/CrossEntry;
.super Landroid/app/Activity;
.source "CrossEntry.java"

# v0.3 跨组件 fixture（源入口）：
# onCreate      → new Intent(ctx, CrossTarget.class) + putExtra(可控) → startActivity（应建边）
# onStart       → setClassName(String, String) + putExtra(可控)      → startActivity（应建边）
# onNewIntent   → new ComponentName(pkg, cls) + setComponent        → startActivity（应建边）
# onResume      → 显式 Intent，但不带数据                          → startActivity（不应建边）
# onReceive     → 隐式 action Intent，带可控数据                    → startActivity（无目标，不应建边）

.method public onCreate(Landroid/os/Bundle;)V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/CrossEntry;->getIntent()Landroid/content/Intent;
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
    invoke-virtual {p0, v3}, Lcom/example/app/CrossEntry;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onStart()V
    .locals 5

    invoke-virtual {p0}, Lcom/example/app/CrossEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    invoke-direct {v3}, Landroid/content/Intent;-><init>()V
    const-string v4, "com.example.app"
    const-string v0, "com.example.app.CrossTarget"
    invoke-virtual {v3, v4, v0}, Landroid/content/Intent;->setClassName(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/CrossEntry;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onNewIntent(Landroid/content/Intent;)V
    .locals 6

    invoke-virtual {p0}, Lcom/example/app/CrossEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v2

    new-instance v3, Landroid/content/Intent;
    invoke-direct {v3}, Landroid/content/Intent;-><init>()V
    const-string v4, "com.example.app"
    const-string v5, "com.example.app.CrossTarget"
    new-instance v0, Landroid/content/ComponentName;
    invoke-direct {v0, v4, v5}, Landroid/content/ComponentName;-><init>(Ljava/lang/String;Ljava/lang/String;)V
    invoke-virtual {v3, v0}, Landroid/content/Intent;->setComponent(Landroid/content/ComponentName;)Landroid/content/Intent;
    invoke-virtual {v3, v1, v2}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v3}, Lcom/example/app/CrossEntry;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onResume()V
    .locals 2

    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/example/app/CrossTarget;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {p0, v0}, Lcom/example/app/CrossEntry;->startActivity(Landroid/content/Intent;)V
    return-void
.end method

.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .locals 3

    invoke-virtual {p0}, Lcom/example/app/CrossEntry;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-virtual {v0}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    const-string v1, "url"
    invoke-virtual {v0, v1}, Landroid/net/Uri;->getQueryParameter(Ljava/lang/String;)Ljava/lang/String;
    move-result-object v1

    new-instance v2, Landroid/content/Intent;
    const-string v0, "android.intent.action.VIEW"
    invoke-direct {v2, v0}, Landroid/content/Intent;-><init>(Ljava/lang/String;)V
    invoke-virtual {v2, v1, v1}, Landroid/content/Intent;->putExtra(Ljava/lang/String;Ljava/lang/String;)Landroid/content/Intent;
    invoke-virtual {p0, v2}, Lcom/example/app/CrossEntry;->startActivity(Landroid/content/Intent;)V
    return-void
.end method
