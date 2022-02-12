import asyncio
import re
import time
import traceback
import logging
import gitlab

privateToken = 'your-api-token'
gitlabUrl = 'https://your.gitlab.domain'

MAIN_ITERATE_DELAY = 5
PROJECT_GATHERING_DELAY = 60 * 10

PIPELINE_TIMEOUT_SECONDS = 1.5 * 3600
MERGE_STATUS_TIMEOUT_SECONDS = 30
MERGE_TIMEOUT_SECONDS = 30
REBASE_TIMEOUT_SECONDS = 30

gl = gitlab.Gitlab(gitlabUrl, private_token=privateToken)
gl.auth()

botUserId = gl.user.id

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%m/%d/%Y %H:%M:%S', level=logging.INFO)

class BotException(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def getAccessibleUsersOfProject(project):
    if project.id == 52:  # your project id
        return [33, 3] # id of users which have permission to merge
    return None # allow anyone


def ensureMergeable(project, mergeRequestId):
    mergeRequest = getMergeRequestById(project, mergeRequestId)

    allowedUsersId = getAccessibleUsersOfProject(project)
    if allowedUsersId is not None and mergeRequest.author['id'] not in allowedUsersId:
        raise BotException("Sorry, you dont have permission to merge this project!")

    if mergeRequest.target_branch not in ['main', 'master']:
        raise BotException("As a security check I only accept merge requests to main or master")

    if mergeRequest.source_project_id != mergeRequest.target_project_id:
        raise BotException("Sorry, Cant merge to different project!")

    if mergeRequest.work_in_progress:
        raise BotException("Sorry, I can't merge requests marked as Work-In-Progress!")

    # TODO  check if approved

    if not mergeRequest.blocking_discussions_resolved:
        raise BotException("Sorry, I can't merge requests which have unresolved discussions!")

    state = mergeRequest.state
    if state != 'opened':
        if state in ('merged', 'closed'):
            raise Exception(f'The merge request is already {state}!')
        raise BotException(f'The merge request is in an unknown state: {state}')

    if mergeRequest.assignee and mergeRequest.assignee.get('id') != botUserId:
        raise BotException('It is not assigned to me anymore!')


async def waitForRebaseToComplete(project, mergeRequestId):
    start = time.time()
    while True:
        if time.time() - start > REBASE_TIMEOUT_SECONDS:
            raise BotException('Rebasing timed out')
        await asyncio.sleep(2)
        mr = getMergeRequestById(project, mergeRequestId, includeRebase=True)
        if not mr.rebase_in_progress:
            break
        logging.info('waiting for rebase to be done')


async def rebaseIfNeeded(project, mergeRequestId):
    if project.merge_method != 'merge':
        mr = getMergeRequestById(project, mergeRequestId, includeDivergedCommits=True)
        if mr.diverged_commits_count > 0:
            logging.info("need rebase")
            mr.rebase()
            await waitForRebaseToComplete(project, mergeRequestId)


def getMergeRequestById(project, mergeRequestId, includeRebase=False, includeDivergedCommits=False):
    return project.mergerequests.get(id=mergeRequestId, include_rebase_in_progress=includeRebase,
                                     include_diverged_commits_count=includeDivergedCommits)


async def waitForPipleIfNeeded(project, mergeRequestId):
    delay = 5
    if project.only_allow_merge_if_pipeline_succeeds:
        logging.info("checking pipeline status")
        start = time.time()
        while True:
            if time.time() - start > PIPELINE_TIMEOUT_SECONDS:
                raise BotException('Pipeline timed out')
            mergeRequest = getMergeRequestById(project, mergeRequestId)
            sha = mergeRequest.sha
            pipelines = mergeRequest.pipelines.list()
            currentPipeline = next(iter(pipeline for pipeline in pipelines if pipeline.sha == sha), None)
            ciStatus = currentPipeline.status
            if ciStatus == 'success':
                break
            elif ciStatus == 'skipped':
                if project.allow_merge_on_skipped_pipeline:
                    break
                else:
                    raise BotException('ci skipped')
            elif ciStatus in ('failed', 'canceled'):
                raise BotException('ci failed or canceled')
            logging.info(f'waiting for ci to be done current status: {ciStatus}')
            await asyncio.sleep(delay)
            if delay < 60:
                delay += 5


async def waitForMergeCheckingDone(project, mergeRequestId):
    delay = 5
    start = time.time()
    while True:
        if time.time() - start > MERGE_STATUS_TIMEOUT_SECONDS:
            raise BotException('Pipeline timed out')
        mergeRequest = getMergeRequestById(project, mergeRequestId)
        if mergeRequest.merge_status not in ['unchecked', 'checking']:
            break
        logging.info(f'waiting for merge_status to be calculated')
        await asyncio.sleep(delay)


def acceptMerge(project, mergeRequestId):
    logging.info('start merging')
    try:
        getMergeRequestById(project, mergeRequestId).merge()
    except gitlab.GitlabHttpError as e:
        logging.error(f'merge error: "{e.response_body}"')
        if e.response_code == 405:
            raise BotException("cannot merge because one of Draft, Closed, Pipeline Pending Completion, or Failed while requiring Success")
        elif e.response_code == 406:
            raise BotException("cannot merge because of a conflict")
        elif e.response_code == 409:
            raise BotException("cannot merge because of the sha parameter is passed and does not match the HEAD")
        elif e.response_code == 401:
            raise BotException("cannot merge because you dont have permission to merge")
        else:
            raise


async def waitForMergeGetDone(project, mergeRequestId):
    start = time.time()
    while True:
        if time.time() - start > MERGE_TIMEOUT_SECONDS:
            raise BotException('Pipeline timed out')
        await asyncio.sleep(2)
        mr = getMergeRequestById(project, mergeRequestId)
        if mr.state == 'merged':
            logging.info('congrate. its merged!')
            break
        logging.info(f'waiting for merge to be done. current status {mr.state}')


async def rebaseSourceBranch(project, mergeRequestId):
    logging.info('moving merge commit to source branch by rebasing')
    mergedMr = getMergeRequestById(project, mergeRequestId)
    mr = project.mergerequests.create({'source_branch': mergedMr.source_branch,
                                       'target_branch': mergedMr.target_branch,
                                       'title': f'rebasing branch {mergedMr.source_branch} into {mergedMr.target_branch}'})
    mr.rebase(skip_ci=True)
    logging.info(f'source branch rebased using mr: {mr.iid}')
    await waitForRebaseToComplete(project, mr.iid)
    mr.state_event = 'close'
    mr.save()
    logging.info('source branch rebasing finished')


def unassignMergeRequest(project, mergeRequestId):
    mr = getMergeRequestById(project, mergeRequestId)
    if mr.author['id'] == botUserId:
        mr.assignee_id = 0
    else:
        mr.assignee_id = mr.author['id']
    mr.save()


def sendCommentToMergeRequest(project, mergeRequestId, comment):
    mr = getMergeRequestById(project, mergeRequestId)
    mr.notes.create({'body': comment})


def createTagIfNeeded(project, mergeRequestId):
    mr = getMergeRequestById(project, mergeRequestId)
    comments = mr.notes.list(per_page=50)
    ids = getAccessibleUsersOfProject(project)
    for comment in comments:
        if comment.author['id'] in ids:
            m = comment.body
            if m.startswith('tag'):
                logging.info('It seems I need to tag something')
                lines = re.split(r'[\r\n]+', m)
                tagParts = lines[0].split(':')
                if len(tagParts) != 2:
                    raise BotException(f'I expect first line of a tag comment be splited by single ":"' +
                                       f' but it wasnt. current len: {len(tagParts)}')
                tagName = tagParts[1].strip()
                if not re.match(r'v?[\d.]+', tagName):
                    raise BotException(f'I expect tag name in form of v?[\d\.]+ but its: {tagName}')
                releaseNotes = [re.sub(r'(^[\s*+-]+)|(\s+$)', '', p) for p in lines[1:]]
                releaseNotes = [r for r in releaseNotes if r]
                project.tags.create({'tag_name': tagName, 'ref': mr.target_branch})
                project.releases.create(
                    {'name': tagName, 'tag_name': tagName, 'description': '  \n'.join(releaseNotes)})
                logging.info(f'Hora! I have created tag {tagName}')


async def processMergeRequest(project, mergeRequestId):
    try:
        ensureMergeable(project, mergeRequestId)

        await rebaseIfNeeded(project, mergeRequestId)

        # do we really need this?
        # Make sure no-one managed to race and push to the branch in the

        # self.maybe_reapprove(merge_request, approvals)

        await waitForPipleIfNeeded(project, mergeRequestId)

        await waitForMergeCheckingDone(project, mergeRequestId)

        # do we really need this?
        ensureMergeable(project, mergeRequestId)

        acceptMerge(project, mergeRequestId)

        await waitForMergeGetDone(project, mergeRequestId)

        await rebaseSourceBranch(project, mergeRequestId)

        createTagIfNeeded(project, mergeRequestId)

    except BotException as e:
        unassignMergeRequest(project, mergeRequestId)
        sendCommentToMergeRequest(project, mergeRequestId, e.message)


async def processProject(project):
    while True:
        try:
            mergeRequests = project.mergerequests.list(assignee_id=botUserId, state="opened")
            for mergeRequest in mergeRequests:
                if mergeRequest.assignee and mergeRequest.assignee.get('id') == botUserId:
                    logging.info(f'Hey this merge request is mine id: {mergeRequest.iid} - title: "{mergeRequest.title}"')
                    await processMergeRequest(project, mergeRequest.iid)
            await asyncio.sleep(MAIN_ITERATE_DELAY)
        except:
            logging.error(f'something went wrong in project {project.name}')
            traceback.print_exc()
            raise


async def main():
    asyncTasks = {}
    while True:
        projects = gl.projects.list()
        projectIds = [p.id for p in projects]
        for id, task in asyncTasks.items():
            if id not in projectIds:
                logging.error(f'stop monitoring project id {id}')
                task.cancel()

        for project in projects:
            if project.id not in asyncTasks:
                logging.info(f'start monitoring {project.id}:{project.name}')
                asyncTasks[project.id] = asyncio.create_task(processProject(project))

        for id in list(asyncTasks.keys()):
            task = asyncTasks[id]
            if task.done():
                logging.warning(f'removing task for project id {id}')
                del asyncTasks[id]

        await asyncio.sleep(PROJECT_GATHERING_DELAY)


asyncio.run(main())
