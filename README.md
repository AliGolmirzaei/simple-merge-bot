# simple merge bot

This project is a very simple GitLab merge robot. I intentionally kept the code very simple to make it easily understandable and get forked and developed.

# What it does
* First the bot monitor all projects it is a member of
* Then it monitors all merge request which is assigned to him
* On assigning a merge request it starts the process of merging by checking if a rebase is required or not. It detects such cases by checking the merge method of GitLab. On linear and semi-linear history it is needed to rebase the branch first which is done by the robot.
* Then it checks if a successful pipeline is needed for merge request or not (it is defined in GitLab project > Setting > General > Merge checks). If a successful pipeline is needed it waits for the pipeline to complete successfully
* Then it checks if the branch is mergeable. There are multiple checkings here
  * First we can define some kind of authority that only accept merge request if they are created by someone specific. By default bot allows everyone
  * Then we can allow only a specific branch as the destination. By default, it only allows merging into main and master.
  * Currently the bot doesn't allow to merge to a different project
  * And finally it checks for some states. Work in progress MRs are not allowed to merge. If there are unresolved discussions it's not allowed to merge. If MR status is not open it cannot be merged. If the assignee of MR gets changed during the procedure it stops merging
* At this step bot tries to accept the merge 
* If merge is successful and merge methods is semi-linear it tries to bring the merge commit which is getting created in the destination branch to the source branch
* Then it checks messages in MR and if there is a message started with "tag" text it tries to create the tag with release notes defined in the message

# How to run it
* First create a user in your GitLab for the bot. 
* Then get the API token of the bot user. 
* Make bot a maintainer of your project. 
* Edit the main.py and put API token and your GitLab URL in `privateToken` and `gitlabUrl` respectively
* Run the bot with python3 main.py. I personally run it inside a docker container
* Enjoy!
