.class public Lcom/example/app/Bad;
.super Ljava/lang/Object;

.bogus-directive whatever

# virtual methods
.method public broken()V
    .registers 1

    .weird-directive 42

    return-void
.end method

stray-instruction v0
