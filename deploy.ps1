param(
    [string]$EcrRepositoryName = "academicwrite-app",
    [string]$Region = "us-east-1"
)

Write-Host "Building Docker image..." -ForegroundColor Green
docker build -t $EcrRepositoryName .

$repoUri = aws ecr describe-repositories --repository-names $EcrRepositoryName --region $Region --query "repositories[0].repositoryUri" --output text
if (-not $repoUri) {
    Write-Host "Creating ECR repository..." -ForegroundColor Yellow
    $repoUri = aws ecr create-repository --repository-name $EcrRepositoryName --region $Region --query "repository.repositoryUri" --output text
}

Write-Host "Tagging image..." -ForegroundColor Green
docker tag $EcrRepositoryName`:latest $repoUri`:latest

Write-Host "Logging in to ECR..." -ForegroundColor Green
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin ($repoUri -replace "/$EcrRepositoryName.*", "")

Write-Host "Pushing image..." -ForegroundColor Green
docker push $repoUri`:latest

Write-Host "Deployment complete! Image pushed to: $repoUri" -ForegroundColor Green
Write-Host "Next: update your ECS service or Elastic Beanstalk with the new image." -ForegroundColor Cyan