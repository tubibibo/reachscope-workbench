.class public Lcom/example/app/NonEntryTarget;
.super Landroid/app/Activity;
.source "NonEntryTarget.java"

# `onCreate` 把 Intent 转交给 `handleIntent` —— 后者不是入口方法名，
# 只能靠"从入口出发、深度 ≤ 4"被发现（D-064）。
.method public onCreate(Landroid/os/Bundle;)V
    .locals 1

    invoke-virtual {p0}, Landroid/app/Activity;->getIntent()Landroid/content/Intent;
    move-result-object v0
    invoke-direct {p0, v0}, Lcom/example/app/NonEntryTarget;->handleIntent(Landroid/content/Intent;)V
    return-void
.end method

.method private handleIntent(Landroid/content/Intent;)V
    .locals 1

    invoke-virtual {p1}, Landroid/content/Intent;->getData()Landroid/net/Uri;
    move-result-object v0
    invoke-virtual {v0}, Landroid/net/Uri;->toString()Ljava/lang/String;
    move-result-object v0
    invoke-virtual {p0, v0}, Landroid/webkit/WebView;->loadUrl(Ljava/lang/String;)V
    return-void
.end method
