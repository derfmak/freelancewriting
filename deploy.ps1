# Parameters
param(
    [string] = "academicwrite-app",
    [string] = "us-east-1",
    [string] = "academicwrite-cluster",
    [string] = "academicwrite-service"
)

Write-Host "Building Docker image..." -ForegroundColor Green
docker build -t  .

 = aws ecr describe-repositories --repository-names  --region  --query "repositories[0].repositoryUri" --output text
if (-not ) {
    Write-Host "Repository doesn't exist. Creating..." -ForegroundColor Yellow
     = aws ecr create-repository --repository-name  --region  --query "repository.repositoryUri" --output text
}

 = ":latest"
Write-Host "Tagging image as " -ForegroundColor Green
docker tag :latest 

Write-Host "Logging in to ECR..." -ForegroundColor Green
aws ecr get-login-password --region  | docker login --username AWS --password-stdin 

Write-Host "Pushing image to ECR..." -ForegroundColor Green
docker push 

Write-Host "Updating ECS service..." -ForegroundColor Green
aws ecs update-service --cluster  --service  --force-new-deployment --region 

Write-Host "Deployment complete!" -ForegroundColor Green
